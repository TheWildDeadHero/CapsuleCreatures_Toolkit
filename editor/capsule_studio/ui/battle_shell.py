"""!The battle editor window: a PanelHost for battle data panels.

The window owns the BattleProject (battle manifest, its ruleset, and the
structure and effect sources it names), the File and Edit menus and the
status bar. A navigator on the left groups the pages:

  - Content: Species, Moves, Types, Parties, Presenters, Passives / Items,
    Data;
  - Structure: Record, Stats & Stages, Categories, Type chart, Flags & Tags,
    Conditions, Formats & Turn, Progression, Terms, Text;
  - Logic: Effects, Formulas, Pipelines & Points, Bench.

Pages whose editors are not built yet say what they will edit and which
work package builds them (editors/battle_common.PlannedPanel). Page titles
use the game's words (a game that calls parties "Trainer" gets a Trainers
page). The battle-structure and battle-logic launchers open this window with
their group in front; the Studio's Battle page is this window too.

Each document keeps its own undo history; Undo / Redo act on the active
page's current document (the content pages edit the battle manifest,
battle.json; the structure pages the structure manifest it names,
structure.json; the Formulas and Pipelines & Points pages the ruleset,
the Effects page an effect source; planned pages none; no page is planned
now). The navigator's second column names the file each group edits (a
page whose file is another one names its own), with " *" while it has unsaved
changes; the status bar names the active page's file. An edit that changes
both manifests is one undo step of each (core.battle); undoing it from either
file undoes newer steps of the other file first (core.document: lock step).
Save writes the active page's file and every unsaved file of its grouped
edits (a rename that rewrote structure.json, sources and bench scenarios is
never saved in part); Save all, the window title's " *" and the prompt
before closing or opening other data count the Bench page's scenarios too.
Opening single-file battle data (the form from an older version) offers to split it into
battle.json + structure.json (core.battle.split(); never asked headless: the
failure is reported); opening pre-E6a stage or chart data offers to migrate
it (File > Migrate stages and chart does it any time; the CLI's `battle FILE
migrate`). Headless nothing waits for a click: a failure goes to the status
bar and the log, a question takes its safe answer (keep the data). Panels
never open files or talk to each other.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

from ..core import codepage, engine
from ..core import battle as battle_core
from ..core.battle import BattleProject, NeedsSplit
from ..core.document import DocumentError, unsaved_group_files
from ..core.structure import stages as stage_model
from .editors.content.data import DataPanel
from .editors.content.moves import MovesPanel
from .editors.content.parties import PartiesPanel
from .editors.content.holders import PassivesItemsPanel
from .editors.content.messages import MessagesPanel
from .editors.content.presenters import PresentersPanel
from .editors.content.species import SpeciesPanel
from .editors.content.type_chart import TypesPanel
from .editors.content.test_save import TestSavePanel
from .editors.logic.ai_panel import AiPanel
from .editors.logic.bench_panel import BenchPanel
from .editors.logic.effects_panel import EffectsPanel
from .editors.logic.formulas import RulesPanel
from .editors.logic.pipelines import PipelinesPointsPanel
from .editors.structure.categories import CategoriesPanel
from .editors.structure.chart import TiersChartPanel
from .editors.structure.combination import CombinationPanel
from .editors.structure.conditions import ConditionsPanel
from .editors.structure.delayed_hits import DelayedHitsPanel
from .editors.structure.encounter_rules import EncounterRulesPanel
from .editors.structure.field_actions import FieldActionsPanel
from .editors.structure.field_effects import FieldEffectsPanel
from .editors.structure.flags import FlagsTagsPanel
from .editors.structure.nursery import NurseryPanel
from .editors.structure.passive_slots import PassiveSlotsPanel
from .editors.structure.pockets import PocketsPanel
from .editors.structure.recruit import RecruitPanel
from .editors.structure.species_fields import SpeciesFieldsPanel
from .editors.structure.progression import ProgressionPanel
from .editors.structure.turn import FormatsPanel, TurnPanel
from .editors.structure.record import RecordPanel
from .editors.structure.stages import StagesPanel
from .editors.structure.resources import ResourcesPanel
from .editors.structure.stats import StatsPanel
from .editors.structure.step_effects import StepEffectsPanel
from .editors.structure.storage import StoragePanel
from .editors.structure.terms import TermsPanel
from .editors.structure.text import CodePageLinkPanel
from .editors.structure.transformation import TransformationPanel
from . import profiler
from .panel import EditorPanel
from .panes import NARROW, WIDE, fit_panel, splitter
from .widgets import STATUS_MS, StartPage, ask, file_toolbar, headless, remember_file, report_failure

if TYPE_CHECKING:
   from ..core.document import Document
   from .project_shell import ProjectWindow

## A navigator group: (id, title, its panel classes in page order).
NavGroup = tuple[str, str, list[type[EditorPanel]]]

## The navigator's groups, in order.
NAV_GROUPS: list[NavGroup] = [
   ("content", "Content", [SpeciesPanel, MovesPanel, TypesPanel, PartiesPanel, PresentersPanel, PassivesItemsPanel,
                           TestSavePanel, MessagesPanel, DataPanel]),
   ("structure", "Structure", [RecordPanel, StatsPanel, ResourcesPanel, PassiveSlotsPanel, SpeciesFieldsPanel,
                               PocketsPanel, RecruitPanel, StoragePanel, StagesPanel, CategoriesPanel,
                               TiersChartPanel, FlagsTagsPanel,
                               ConditionsPanel, DelayedHitsPanel, FormatsPanel, TurnPanel, ProgressionPanel,
                               TransformationPanel, FieldEffectsPanel, EncounterRulesPanel, FieldActionsPanel,
                               StepEffectsPanel, CombinationPanel, NurseryPanel, TermsPanel, CodePageLinkPanel]),
   ("logic", "Logic", [EffectsPanel, RulesPanel, PipelinesPointsPanel, AiPanel, BenchPanel]),
]
## Group ids (battle_app --group, BattleWindow's group).
GROUP_IDS = [g[0] for g in NAV_GROUPS]
## The file each navigator group edits: the BattleProject attribute holding its Document.
GROUP_FILES = {"content": "battle", "structure": "structure", "logic": "ruleset"}
## Navigator column of the group and page titles.
TITLE_COLUMN = 0
## Navigator column naming the file a group edits (or a page, when it edits another one).
FILE_COLUMN = 1
## Navigator columns.
NAV_COLUMNS = 2
## After a file name with unsaved changes.
DIRTY_MARK = " *"
## Battle panels, in navigator order.
BATTLE_PANELS = [cls for _gid, _title, classes in NAV_GROUPS for cls in classes]
## Id and title of the group of hosted panels that belong to no navigator group (plugins, tests).
OTHER_GROUP = ("other", "Other")
## File dialog filter.
BATTLE_FILTER = "Battle data (battle.json *.json);;All files (*)"
## Width of the window when it opens, pixels.
WINDOW_WIDTH = 1200
## Height of the window when it opens, pixels.
WINDOW_HEIGHT = 780
## Starting width of the navigator, pixels (titles and file names; the user drags its boundary).
NAV_WIDTH = 290
## Item data role of a navigator page: the index of its panel in BattleWindow.panels (groups have none).
PANEL_ROLE = QtCore.Qt.ItemDataRole.UserRole
## Status bar text while the battle data compiles for every target.
COMPILES_TEXT = "battle data compiles"
## What opening or creating battle data may raise (the data or a page that cannot show it, the files, the engine).
OPEN_ERRORS = (DocumentError, OSError, ValueError, engine.EngineNotFound)
## Most characters of a compile error the status bar shows (the full text is its tool tip).
STATUS_ERROR_CHARS = 120


class BattleWindow(QtWidgets.QMainWindow):
   """!Main window hosting battle panels (implements PanelHost, see panel.py)."""

   def __init__(self, panel_classes: Sequence[type[EditorPanel]] | None = None, path: str | Path | None = None,
                group: str | None = None) -> None:
      """!Creates the window.
      @param panel_classes  panels to host (default: BATTLE_PANELS)
      @param path           battle.json to open, or None
      @param group          navigator group to show first (one of GROUP_IDS; the others start collapsed), or
                            None for the first page
      """
      super().__init__()
      if group is not None and group not in GROUP_IDS:
         raise ValueError(f"unknown group {group!r} (groups: {', '.join(GROUP_IDS)})")
      ## The open BattleProject, or None.
      self.project = None
      ## Why the last open (or new battle data) failed, or None.
      self.open_error = None
      ## (undo label, message) of the last edit run_edit() refused, or None after one that went through.
      self.edit_error = None
      ## A refresh is scheduled (see changed()).
      self._refresh_pending = False
      ## Unused by battle panels; present for the PanelHost contract.
      self.reports = None
      ## The hosted EditorPanel instances, in page order.
      self.panels = []
      ## Opens the project's Code page panel (the Text page's button); the Studio replaces it with its
      ## Project page's.
      self.open_code_page: Callable[[], None] = lambda: self._open_code_page_window()
      ## The project settings window open_code_page() opened, or None.
      self._code_page_window: ProjectWindow | None = None
      ## The page navigator: one top-level item per group, one child per page.
      self.nav = QtWidgets.QTreeWidget()
      self.nav.setColumnCount(NAV_COLUMNS)
      self.nav.setHeaderHidden(True)
      self.nav.setRootIsDecorated(True)
      header = self.nav.header()
      header.setStretchLastSection(False)
      header.setSectionResizeMode(TITLE_COLUMN, QtWidgets.QHeaderView.ResizeMode.Stretch)
      header.setSectionResizeMode(FILE_COLUMN, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
      ## The pages (index = panels index).
      self.stack = QtWidgets.QStackedWidget()
      ## Navigator group items by group id.
      self.group_items = {}
      ## Navigator page items, one per panel (index = panels index).
      self.page_items = []
      self._build_menus()   # before the pages: their signals update the menus
      ## The latest compile result for every target, kept in the status bar (update_compile_status()).
      self.compile_status = QtWidgets.QLabel()
      ## The file the active page edits ("Editing structure.json *"), in the status bar.
      self.file_status = QtWidgets.QLabel()
      self.statusBar().addPermanentWidget(self.file_status)
      self.statusBar().addPermanentWidget(self.compile_status)
      self._build_pages(list(panel_classes or BATTLE_PANELS))
      ## Start page, shown until battle data is open.
      self.start = StartPage(
         "CapsuleCreatures Battle Editor",
         "Open a game's battle data (its battle.json) or create new battle data to start editing its content "
         "(species, moves, types, parties, presenters), its structure and its logic.",
         [("Open battle data...", lambda: self.open_battle()), ("New battle data...", lambda: self.new_battle())],
         "battle-editor", lambda path: self.open_battle(path),
         skip=("Continue without battle data", lambda: self.show_editor()), recent_title="Recent battle data")
      if len(self.panels) > 1:
         # [RZ] the navigator and the page are panes: drag the boundary (the navigator starts NAV_WIDTH wide)
         ## The navigator | page splitter.
         self.split = splitter(QtCore.Qt.Orientation.Horizontal, [self.nav, self.stack], [NARROW, WIDE],
                               [NAV_WIDTH, None])
         self.setCentralWidget(self.split)
      else:   # one editor alone (battle-editor --panel): no navigator
         self.setCentralWidget(self.panels[0])
      self.nav.currentItemChanged.connect(lambda item, _old: self._nav_changed(item))
      self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
      if group is not None and group in self.group_items:
         self.show_group(group)
      elif self.page_items:
         self.nav.setCurrentItem(self.page_items[0])
      self._update_title()
      if path:
         self.open_battle(path)

   def _build_pages(self, classes: list[type[EditorPanel]]) -> None:
      """!Creates the panels and the navigator: the groups in NAV_GROUPS order, each with its hosted pages
      (a group with none is left out), then the pages no group names.
      @param classes  panel classes to host
      @return None
      """
      grouped = [(gid, title, [c for c in members if c in classes]) for gid, title, members in NAV_GROUPS]
      known = {c for _gid, _title, members in grouped for c in members}
      grouped.append(OTHER_GROUP + ([c for c in classes if c not in known],))
      bold = self.nav.font()
      bold.setBold(True)
      for gid, title, members in grouped:
         if not members:
            continue
         group_item = QtWidgets.QTreeWidgetItem([title])
         group_item.setFont(TITLE_COLUMN, bold)
         group_item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)   # a heading: picking it shows nothing
         self.nav.addTopLevelItem(group_item)
         self.group_items[gid] = group_item
         for cls in members:
            panel = cls(self)
            fit_panel(panel)   # [RZ] scroll bars instead of a window larger than the screen
            item = QtWidgets.QTreeWidgetItem([panel.title])
            item.setData(0, PANEL_ROLE, len(self.panels))
            group_item.addChild(item)
            self.panels.append(panel)
            self.page_items.append(item)
            self.stack.addWidget(panel)
         group_item.setExpanded(True)

   # -- navigator --------------------------------------------------------------------

   def group_of(self, panel: EditorPanel) -> str:
      """!The navigator group a hosted panel is in.
      @param panel  a panel of this window
      @return group id (one of GROUP_IDS, or OTHER_GROUP's)
      """
      parent = self.page_items[self.panels.index(panel)].parent()
      return next(gid for gid, item in self.group_items.items() if item is parent)

   def show_panel(self, panel: EditorPanel | str) -> EditorPanel:
      """!Brings a page to the front (its group opens).
      @param panel  a panel of this window, or its panel_id
      @return the panel
      @throws KeyError when the window hosts no such panel
      """
      if isinstance(panel, str):
         found = [p for p in self.panels if p.panel_id == panel]
         if not found:
            raise KeyError(panel)
         panel = found[0]
      item = self.page_items[self.panels.index(panel)]
      item.parent().setExpanded(True)
      self.nav.setCurrentItem(item)
      return panel

   def show_group(self, group: str) -> EditorPanel:
      """!Brings a group's first page to the front; the other groups collapse.
      @param group  group id
      @return the panel in front
      @throws KeyError when the window hosts no page of that group
      """
      first = self.group_items[group].child(0)
      for gid, item in self.group_items.items():
         item.setExpanded(gid == group)
      self.nav.setCurrentItem(first)
      return self.panels[first.data(0, PANEL_ROLE)]

   def page_title(self, panel: EditorPanel) -> str:
      """!A page's title as the navigator shows it (in the game's words).
      @param panel  a panel of this window
      @return text
      """
      return self.page_items[self.panels.index(panel)].text(0)

   def page_titles(self) -> list[str]:
      """!Every page's navigator title, in page order.
      @return list of str
      """
      return [item.text(0) for item in self.page_items]

   def _nav_changed(self, item: QtWidgets.QTreeWidgetItem | None) -> None:
      """!The navigator's current item changed: show its page.
      @param item  QTreeWidgetItem, or None
      @return None
      """
      index = item.data(0, PANEL_ROLE) if item is not None else None
      if index is None:
         return   # a group heading
      self.stack.setCurrentIndex(index)
      self._page_changed(index)

   def _open_code_page_window(self) -> None:
      """!Opens the project settings window of the game the battle data is in, with its Code page panel in
      front (open_code_page() outside the Studio).
      @return None
      """
      found = codepage.find_project(self.project.battle.path) if self.project is not None else None
      if found is None:
         self.show_status("This battle data is not inside a game (no reference/project.json): nothing to open.")
         return
      from .project_shell import ProjectWindow   # local: only this button needs the project settings window
      w = self._code_page_window
      if w is None or not w.isVisible() or w.document is None or w.document.path != found.resolve():
         w = self._code_page_window = ProjectWindow(found)
      w.show_panel("codepage")
      w.show()
      w.raise_()
      w.activateWindow()

   def dialog_parent(self) -> QtWidgets.QWidget:
      """!Window dialogs belong to: the start window while it is the one shown.
      @return QWidget
      """
      return self.start if self.start.isVisible() else self

   def show_editor(self) -> None:
      """!Shows the editor window (with or without battle data open) instead of the start window.
      @return None
      """
      self.start.hide()
      self.show()
      if self.project is None:
         self.show_status("No battle data open: File > Open battle data... or New battle data...")

   def launch(self) -> None:
      """!Shows the editor when something is open, else the start window
      (closing that one ends the program).
      @return None
      """
      if self.project is not None:
         self.show()
      else:
         self.start.refresh()
         self.start.show()

   # -- PanelHost -------------------------------------------------------------------

   @property
   def document(self) -> Document | None:
      """!The active panel's current document (for Undo / Redo).
      @return Document, or None
      """
      return self.page_document(self.active_panel())

   def page_document(self, panel: EditorPanel | None) -> Document | None:
      """!The document a page edits now (its current_document()).
      @param panel  a panel of this window, or None
      @return Document, or None (nothing open, or a page without one)
      """
      if panel is None or self.project is None:
         return None
      # A panel that does not override current_document() has no document of its own here.
      if type(panel).current_document is EditorPanel.current_document:
         return None   # the default would ask the host again
      return panel.current_document()

   def group_document(self, group: str) -> Document | None:
      """!The file a navigator group edits (GROUP_FILES).
      @param group  group id
      @return Document, or None (nothing open, or a group without one)
      """
      attr = GROUP_FILES.get(group)
      return getattr(self.project, attr, None) if self.project is not None and attr is not None else None

   @staticmethod
   def file_text(doc: Document | None) -> str:
      """!A file's name as the navigator and the status bar show it.
      @param doc  Document, or None
      @return its file name, DIRTY_MARK after it while it has unsaved changes ("" for None)
      """
      if doc is None or doc.path is None:
         return ""
      return doc.path.name + (DIRTY_MARK if doc.dirty else "")

   def _update_files(self) -> None:
      """!The navigator's file column and the status bar's file: each group's file, a page's own when it is
      another one, the active page's.
      @return None
      """
      for gid, item in self.group_items.items():
         item.setText(FILE_COLUMN, self.file_text(self.group_document(gid)))
      for panel, item in zip(self.panels, self.page_items):
         doc = self.page_document(panel)
         gid = self.group_of(panel)
         own = doc is not None and doc is not self.group_document(gid)
         item.setText(FILE_COLUMN, self.file_text(doc) if own else "")
         item.setToolTip(TITLE_COLUMN, f"Edits {doc.path.name}" if doc is not None and doc.path is not None else "")
      doc = self.document
      self.file_status.setText(f"Editing {self.file_text(doc)}" if doc is not None else "")

   def active_panel(self) -> EditorPanel | None:
      """!The panel in front.
      @return EditorPanel, or None
      """
      if len(self.panels) == 1:
         return self.panels[0]
      i = self.stack.currentIndex()
      return self.panels[i] if 0 <= i < len(self.panels) else None

   def show_status(self, text: str) -> None:
      """!Shows a message in the status bar.
      @param text  message
      @return None
      """
      self.statusBar().showMessage(text, STATUS_MS)

   def run_edit(self, label: str, fn: Callable[[], object], document: Document | None = None) -> bool:
      """!Runs fn() inside document.edit(label); a refusal is kept in edit_error and reported without waiting
      for a click headless (widgets.report_failure(): logged, the status bar; a warning box on a screen).
      @param label     undo label
      @param fn        callable
      @param document  Document to edit (default: the active panel's)
      @return True when the edit went through
      """
      doc = document or self.document
      if doc is None:
         return False
      try:
         with doc.edit(label):
            fn()
      except (DocumentError, ValueError, KeyError, IndexError, TypeError, OSError, engine.EngineNotFound) as e:
         self.edit_error = (label, str(e))
         report_failure(self.dialog_parent(), label, str(e))
         self.show_status(f"{label}: {e}")
         return False
      self.edit_error = None
      self.changed()
      return True

   def selection_changed(self) -> None:
      """!The active panel picked another document: update Undo / Redo.
      @return None
      """
      self._update_title()

   def changed(self) -> None:
      """!Refresh every panel once, after the current signal handler returns.
      @return None
      """
      if not self._refresh_pending:
         self._refresh_pending = True
         QtCore.QTimer.singleShot(0, lambda: self._refresh_now())

   def _refresh_now(self) -> None:
      """!Runs the refresh changed() scheduled.
      @return None
      """
      self._refresh_pending = False
      for p in self.panels:
         p.refresh()
      self._update_tab_titles()
      self._update_title()
      self.update_compile_status()

   def update_compile_status(self) -> None:
      """!Shows the latest compile result for every platform the game builds for in the status bar (after
      opening battle data and after every edit, undo and redo).
      @return None
      """
      # Another name for the project: Doxygen 1.12 takes "project.validate...()" here for this class's validate().
      battle = self.project
      error = battle.validate_targets() if battle is not None else None
      text = "" if battle is None else f"compile error: {error}" if error else COMPILES_TEXT
      shown = text if len(text) <= STATUS_ERROR_CHARS else text[:STATUS_ERROR_CHARS] + "..."
      self.compile_status.setText(shown)
      self.compile_status.setToolTip(text)

   def _update_tab_titles(self) -> None:
      """!Page titles in the navigator in the game's words (a panel's tab_title(), when it has one).
      @return None
      """
      for p, item in zip(self.panels, self.page_items):
         title = getattr(p, "tab_title", None)
         item.setText(0, title() if callable(title) else p.title)

   # -- project -------------------------------------------------------------------------

   def _attach(self, project: BattleProject) -> None:
      """!Switches to a project (back to the previous one if a panel can't show it).
      @param project  BattleProject
      @return None
      """
      old, self.project = self.project, project
      try:
         for p in self.panels:
            p.document_replaced()
      except Exception as e:
         self.project = old
         for p in self.panels:
            p.document_replaced()
         self._update_title()
         raise DocumentError(f"cannot show this battle data: {e}") from e
      self._update_tab_titles()
      self.start.hide()
      if not self.isVisible():
         self.show()
      remember_file("battle-editor", project.battle.path)
      self._update_title()
      self.update_compile_status()

   def _update_title(self) -> None:
      """!Window title and Undo / Redo labels.
      @return None
      """
      if self.project is None:
         self.setWindowTitle("CapsuleCreatures Battle Editor")
      else:
         mark = " *" if self.project.dirty else ""
         self.setWindowTitle(f"{self.project.battle.path.name}{mark} - CapsuleCreatures Battle Editor")
      for a in self.project_actions:
         a.setEnabled(self.project is not None)
      self._update_files()
      doc = self.document
      undo = doc.undo_label() if doc is not None else None
      redo = doc.redo_label() if doc is not None else None
      self.save_action.setEnabled(doc is not None and doc.dirty)
      self.save_all_action.setEnabled(self.project is not None and self.project.dirty)
      self.undo_action.setEnabled(undo is not None)
      self.redo_action.setEnabled(redo is not None)
      self.undo_action.setText(f"Undo {undo or ''}".strip())
      self.redo_action.setText(f"Redo {redo or ''}".strip())

   def _action(self, menu: QtWidgets.QMenu, text: str, slot: Callable[[], object],
               shortcut: QtGui.QKeySequence.StandardKey | None = None) -> QtGui.QAction:
      """!Adds a menu action.
      @param menu      QMenu
      @param text      label
      @param slot      callable
      @param shortcut  QKeySequence.StandardKey, or None
      @return QAction
      """
      a = QtGui.QAction(text, self)
      if shortcut is not None:
         a.setShortcuts(shortcut)
      a.triggered.connect(lambda _checked=False: slot())
      menu.addAction(a)
      return a

   def _build_menus(self) -> None:
      """!File and Edit menus.
      @return None
      """
      keys = QtGui.QKeySequence.StandardKey
      m = self.menuBar().addMenu("&File")
      self._action(m, "&New battle data...", lambda: self.new_battle(), keys.New)
      ## Opens battle data.
      self.open_action = self._action(m, "&Open battle data...", lambda: self.open_battle(), keys.Open)
      ## Saves the document being edited (the battle or structure manifest, the ruleset, a source).
      self.save_action = self._action(m, "&Save", lambda: self.save_current(), keys.Save)
      ## Saves every document with changes.
      self.save_all_action = self._action(m, "Save a&ll", lambda: self.save_all(), keys.SaveAs)
      ## Migrates pre-E6a stage and chart data (core.structure.stages.migrate_all()).
      self.migrate_action = self._action(m, "&Migrate stages and chart", lambda: self.migrate())
      ## Actions that need open battle data.
      self.project_actions = [self.save_all_action, self._action(m, "&Validate", lambda: self.validate()),
                              self.migrate_action]
      m.addSeparator()
      self._action(m, "&Quit", lambda: self.close(), keys.Quit)
      m = self.menuBar().addMenu("&Edit")
      ## Undo action.
      self.undo_action = self._action(m, "Undo", lambda: self.undo(), keys.Undo)
      ## Redo action.
      self.redo_action = self._action(m, "Redo", lambda: self.redo(), keys.Redo)
      ## Help > Record performance.
      self.recorder = profiler.add_menu(self, "battle-editor")
      ## Save / Save all / Undo / Redo buttons (the same actions as the menus).
      self.file_bar = file_toolbar(self, [
         ("open", self.open_action, "Open battle data (its battle.json)", "Open"),
         None,
         ("save", self.save_action, "Save the file this page edits (battle.json, structure.json, the ruleset or a "
                                    "source; the status bar names it)"),
         ("save_all", self.save_all_action, "Save every changed file of the battle data"),
         None,
         ("undo", self.undo_action, "Undo the last change in this page's file"),
         ("redo", self.redo_action, "Redo the change you undid")])

   def undo(self) -> None:
      """!Undoes the active document's last edit.
      @return None
      """
      doc = self.document
      if doc is not None and doc.undo():
         self.changed()

   def redo(self) -> None:
      """!Redoes the active document's last undone edit.
      @return None
      """
      doc = self.document
      if doc is not None and doc.redo():
         self.changed()

   def commit_typing(self) -> None:
      """!Commits a value still being typed or spun (spin boxes commit on
      focus loss), so it is saved and counted as a change.
      @return None
      """
      w = QtWidgets.QApplication.focusWidget()
      if w is not None:
         w.clearFocus()

   def _stop_panels(self) -> None:
      """!Commits what is being typed: the focused field, and every page's pending text (an idle timer that has not
      fired yet, e.g. the Effects page's text view, the Bench page's choices).
      @return None
      """
      self.commit_typing()
      for p in self.panels:
         p.stop()

   def _confirm_discard(self) -> bool:
      """!Asks about unsaved changes (after committing what is being typed: _stop_panels()); headless the answer is
      Cancel (the data stays open, nothing is lost: see widgets.ask()).
      @return True to go ahead
      """
      self._stop_panels()
      if self.project is None or not self.project.dirty:
         return True
      b = QtWidgets.QMessageBox.StandardButton
      answer = ask(self, "Unsaved changes", "Save all changes first?", b.Save | b.Discard | b.Cancel, b.Save,
                   b.Cancel)
      if answer == b.Save:
         return self.save_all()
      return answer == b.Discard

   def new_battle(self, template: str | None = None, folder: str | Path | None = None) -> None:
      """!New battle data from a template (ui/new_dialog.py NewDialog: Blank, Starter, ...), copied into a folder
      and opened. With both arguments nothing is asked (tests, scripts).
      @param template  template id, or None to ask
      @param folder    target folder, or None to ask
      @return None
      """
      from .new_dialog import BATTLE, NewDialog, template_registry   # local: only this action needs it

      if not self._confirm_discard():
         return
      game = codepage.find_project(self.project.battle.path) if self.project is not None else None
      dialog = NewDialog(BATTLE, folder, template_registry(game), self.dialog_parent())
      if template is not None and folder is not None:
         if not dialog.select(template) or dialog.create() is None:
            self._open_failed("New battle data", dialog.message.text() or f"no template {template!r}")
            return
      elif dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted or dialog.created is None:
         return
      self.open_battle(dialog.created)

   def open_battle(self, path: str | Path | None = None) -> None:
      """!Opens battle data.
      @param path  battle.json, or None to ask
      @return None
      """
      if not self._confirm_discard():
         return
      if path is None:
         path, _ = QtWidgets.QFileDialog.getOpenFileName(self.dialog_parent(), "Open battle data", "", BATTLE_FILTER)
         if not path:
            return
      self.open_error = None
      try:
         self._attach(BattleProject.open(path))
      except NeedsSplit as e:
         if self._offer_split(e):
            self.open_battle(path)
         return
      except OPEN_ERRORS as e:
         self._open_failed("Open battle data", f"{path}: {e}")
         return
      self._offer_migrate()

   def _offer_migrate(self) -> bool:
      """!Offers to migrate pre-E6a stage and chart data just opened (the engine refuses it; like the split offer).
      Headless nothing is asked: the status bar says File > Migrate stages and chart does it.
      @return True when the data was migrated
      """
      if self.project is None or not stage_model.needs_any_migration(self.project.battle):
         return False
      title = "Migrate stages and chart"
      text = ("This battle data has stage or type chart data of an older version (rules tables, stage_names, a stat's "
              "stage flag, a multiplier chart), which the engine no longer reads. Migrate it now? The values move "
              "into the stages list and the chart's tiers (one undo step).")
      b = QtWidgets.QMessageBox.StandardButton
      if ask(self.dialog_parent(), title, text, b.Yes | b.Cancel, b.Yes, b.Cancel) != b.Yes:
         self.show_status(f"Pre-E6a stage / chart data: File > {title} migrates it")
         return False
      return self.migrate()

   def migrate(self) -> bool:
      """!Migrates pre-E6a stage and chart data (core.structure.stages.migrate_all()) as one undo step.
      @return True when something changed
      """
      if self.project is None:
         return False
      doc = self.project.battle
      done: list[str] = []
      ok = self.run_edit("Migrate stages and chart", lambda: done.extend(stage_model.migrate_all(doc)), doc)
      self.show_status(f"Migrated: {', '.join(done)}" if done else "Nothing to migrate")
      return ok and bool(done)

   def _offer_split(self, refused: NeedsSplit) -> bool:
      """!Asks to split single-file battle data (the form from an older version) into its battle and structure manifests
      (core.battle.split(), the engine's battle_split tool) and splits it on yes. Headless nothing is asked: the
      refusal is reported (open_error, the status bar; `capsule-studio battle FILE split` does it there).
      @param refused  the open() refusal
      @return True when the data was split (open it again)
      """
      title = "Open battle data"
      target = battle_core.split_target(refused.path).name
      if headless():
         self._open_failed(title, str(refused))
         return False
      b = QtWidgets.QMessageBox.StandardButton
      answer = QtWidgets.QMessageBox.question(
         self.dialog_parent(), "Split battle data",
         f"{refused.path.name} holds the battle structure ({', '.join(refused.keys)}) that now lives in its own "
         f"file. Split it into {refused.path.name} + {target}? The values move unchanged.", b.Yes | b.Cancel, b.Yes)
      if answer != b.Yes:
         self._open_failed(title, str(refused))
         return False
      try:
         st_path, keys = battle_core.split(refused.path)
      except DocumentError as e:
         self._open_failed(title, str(e))
         return False
      self.show_status(f"Split {refused.path.name}: {len(keys)} structure key(s) moved to {st_path.name}")
      return True

   def _open_failed(self, title: str, text: str) -> None:
      """!Reports battle data that did not open or could not be made: kept in open_error and the status bar,
      logged, and on a screen also shown in a warning box (never one headless: see widgets.report_failure()).
      @param title  what failed
      @param text   the message
      @return None
      """
      self.open_error = text
      report_failure(self.dialog_parent(), title, text)
      self.show_status(f"{title}: {text}")

   def save_current(self) -> bool:
      """!Saves the document the active page edits, with every unsaved file of its grouped edits
      (core.document.unsaved_group_files(): the partner manifest and the sources a rename rewrote are never left
      behind, so the files on disk always agree).
      @return True when saved
      """
      doc = self.document
      if self.project is None or doc is None:
         return True
      self._stop_panels()
      saved = []
      try:
         for d in unsaved_group_files(doc):
            if d.dirty:
               d.save()
               saved.append(d.path.name)
      except (DocumentError, OSError) as e:
         report_failure(self, "Save", str(e))
         self._update_title()
         return False
      self.show_status(f"Saved {', '.join(saved) or doc.path.name}")
      self._update_title()
      return True

   def save_all(self) -> bool:
      """!Saves every document with changes (the open bench scenarios too: BattleProject.save_all()).
      @return True when saved
      """
      if self.project is None:
         return True
      self._stop_panels()
      try:
         self.project.save_all()
      except (DocumentError, OSError) as e:
         report_failure(self, "Save", str(e))
         self._update_title()
         return False
      self.show_status("Saved")
      self._update_title()
      return True

   def validate(self) -> None:
      """!Compiles for every platform the game builds for and reports.
      @return None
      """
      if self.project is not None:
         error = self.project.validate_targets()
         self.update_compile_status()
         if error:
            report_failure(self, "Validate", error)
         else:
            self.show_status("The battle data compiles.")

   def _page_changed(self, index: int) -> None:
      """!Stops the pages left behind; refreshes Undo / Redo labels for the new active panel.
      @param index  page index
      @return None
      """
      for i, p in enumerate(self.panels):
         if i != index:
            p.stop()
      self._update_title()

   def closeEvent(self, event: QtGui.QCloseEvent) -> None:
      """!Asks about unsaved changes before closing.
      @param event  QCloseEvent
      @return None
      """
      if self._confirm_discard():
         event.accept()
      else:
         event.ignore()
