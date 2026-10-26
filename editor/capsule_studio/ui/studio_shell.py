"""!The Studio window: every editor in one window, on one game.

The Studio opens a game through its project manifest (reference/project.json,
core.project.game_files()) and shows each part of it on a page:

  - World: the map editor's window with the Map and Tileset panels and every
    panel extensions register for the Studio or the map editor
    (plugins.registry.STUDIO_HOSTS): Encounters, Events, Locations, Objects
    and project plugins' panels, which follow the Map tab's map;
  - Assets: the scene editor (animation, text, credits);
  - Scripts: the script editor;
  - Battle: the battle editor, with its own navigator of Content, Structure
    and Logic pages (its Text page opens the Project page's code page);
  - Project: the project settings (build settings, code page).

Studio > New game... (and the start window's New game...) makes a game
folder from a battle data template (ui/new_dialog.py, core.templates) and
opens it.

Studio > Open data file (read-only)... shows any JSON file as a tree
(ui/json_view.py, S5): an imported game's importer data such as
world/scripts/story.json, ui/menus.json or overworld/field.json, which no
page edits.

Each page is the standalone tool's own window, embedded: the tools stay one
code base and run by themselves too (map-editor, encounter-editor,
event-editor, object-editor, location-editor, scene-editor, script-editor,
battle-editor, project-settings). A page is created the first time it is
shown or a file opens in it.

The Studio's menu bar holds its Studio menu, the menus of the page in front
(its File, Edit and other menus; its toolbar and status bar stay on the page)
and the Studio's Help menu (Record performance records the whole Studio).
Only the page in front has keyboard shortcuts, so Ctrl+S saves what you see.

Opening a game opens each file on its page and checks that it did; a page
whose file the game does not name, or whose file did not open, is reset (it
starts empty when shown), so no page keeps another game's file. The Project
page's own Open project... opens a whole game in the Studio. Each other
page's File menu still opens another file on that page alone; its tooltip in
the page list names what it has open. Closing the Studio or opening another
game asks every page with unsaved changes, showing it first.

Pages do not share documents: a flag declared on the Scripts page, say, shows
in the World page's tabs once the scripts are saved.
"""
from __future__ import annotations

import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

from ..core import project as project_core
from ..core.document import DocumentError
from ..plugins import registry
from . import json_view, profiler
from .widgets import StartPage, remember_file, report_failure

if TYPE_CHECKING:
   from .battle_shell import BattleWindow
   from .project_shell import ProjectWindow
   from .script_shell import ScriptWindow
   from .shell import EditorWindow
   from .world_shell import WorldWindow

## File dialog filter for project manifests.
PROJECT_FILTER = "Project manifest (project.json *.json);;All files (*)"
## Application title.
TITLE = "CapsuleCreatures Studio"
## Width of the page list, pixels.
NAV_WIDTH = 150
## Width of the window when it opens, pixels.
WINDOW_WIDTH = 1500
## Height of the window when it opens, pixels.
WINDOW_HEIGHT = 880


def _world_page() -> WorldWindow:
   """!The World page: the map editor's window with the Studio's panels.
   @return WorldWindow
   """
   from .world_shell import WORLD_PANELS, WorldWindow
   return WorldWindow(WORLD_PANELS, None, registry.STUDIO_HOSTS, "World")


def _assets_page() -> EditorWindow:
   """!The Assets page: the scene editor's window.
   @return EditorWindow
   """
   from .shell import EditorWindow
   return EditorWindow()


def _scripts_page() -> ScriptWindow:
   """!The Scripts page: the script editor's window.
   @return ScriptWindow
   """
   from .script_shell import ScriptWindow
   return ScriptWindow()


def _battle_page() -> BattleWindow:
   """!The Battle page: the battle editor's window.
   @return BattleWindow
   """
   from .battle_shell import BattleWindow
   return BattleWindow()


def _project_page() -> ProjectWindow:
   """!The Project page: the project settings window.
   @return ProjectWindow
   """
   from .project_shell import ProjectWindow
   return ProjectWindow()


def _opened_world(w: WorldWindow) -> Path | None:
   """!The world.json a World page has open.
   @param w  WorldWindow
   @return Path, or None
   """
   return w.project.world.path if w.project is not None else None


def _opened_document(w: EditorWindow | ProjectWindow) -> Path | None:
   """!The file an Assets or Project page has open.
   @param w  EditorWindow or ProjectWindow
   @return Path, or None
   """
   doc = getattr(w, "document", None)
   return doc.path if doc is not None else None


def _opened_scripts(w: ScriptWindow) -> Path | None:
   """!The scripts.json a Scripts page has open.
   @param w  ScriptWindow
   @return Path, or None
   """
   return w.project.path if w.project is not None else None


def _opened_battle(w: BattleWindow) -> Path | None:
   """!The battle.json a Battle page has open.
   @param w  BattleWindow
   @return Path, or None
   """
   return w.project.battle.path if w.project is not None else None


class Page:
   """!One page of the Studio: which tool, how to build it and open a file in it."""

   def __init__(self, page_id: str, title: str, factory: Callable[[], QtWidgets.QMainWindow], opener: str,
                file_key: str, opened: Callable[..., Path | None]) -> None:
      """!Describes a page.
      @param page_id   id (--page on the command line)
      @param title     list label
      @param factory   callable() -> the tool's QMainWindow
      @param opener    name of the window's method that opens a file (path)
      @param file_key  core.project.GAME_FILES key it opens, "project" for the manifest itself
      @param opened    callable(window) -> the Path the window has open, or None
      """
      ## Id.
      self.page_id = page_id
      ## List label.
      self.title = title
      ## Builds the window.
      self.factory = factory
      ## Name of the window's open method.
      self.opener = opener
      ## What it opens.
      self.file_key = file_key
      ## What the window has open.
      self.opened = opened


## The Studio's pages, in list order.
PAGES = [
   Page("world", "World", _world_page, "open_world", "maps", _opened_world),
   Page("assets", "Assets", _assets_page, "open_file", "assets", _opened_document),
   Page("scripts", "Scripts", _scripts_page, "open_project", "scripts", _opened_scripts),
   Page("battle", "Battle", _battle_page, "open_battle", "battle", _opened_battle),
   Page("project", "Project", _project_page, "open_project", "project", _opened_document),
]


def page_by_id(page_id: str) -> Page:
   """!A page by its id.
   @param page_id  e.g. "world"
   @return Page
   @throws KeyError when there is none
   """
   for p in PAGES:
      if p.page_id == page_id:
         return p
   raise KeyError(page_id)


class StudioWindow(QtWidgets.QMainWindow):
   """!The Studio: a list of pages on the left, the page in front on the right."""

   def __init__(self, path: str | Path | None = None, page_id: str | None = None) -> None:
      """!Creates the window.
      @param path     reference/project.json to open, or None
      @param page_id  page to show first, or None (World)
      """
      super().__init__()
      ## The open project manifest's path, or None (project_path).
      self._project_path = None
      ## The open game's name, or None (game_name).
      self._game_name = None
      ## Built pages: page id -> the tool's window.
      self.windows = {}
      ## Shortcuts taken from pages not in front: page id -> {QAction: [QKeySequence]}.
      self._parked = {}
      ## Menus of the page in front, as added to the menu bar.
      self._page_menus = []
      ## Page menus the Studio leaves out (their Help: the Studio records performance itself).
      self._skipped_menus = set()
      ## Page list.
      self.nav = QtWidgets.QListWidget()
      self.nav.setFixedWidth(NAV_WIDTH)
      self.nav.setStyleSheet("QListWidget::item { padding: 6px 10px; }")
      for p in PAGES:
         item = QtWidgets.QListWidgetItem(p.title)
         item.setData(QtCore.Qt.ItemDataRole.UserRole, p.page_id)
         item.setToolTip("nothing open")
         self.nav.addItem(item)
      ## Page stack (index = PAGES index; a placeholder until the page is built).
      self.stack = QtWidgets.QStackedWidget()
      for p in PAGES:
         self.stack.addWidget(self._placeholder(p))
      body = QtWidgets.QWidget()
      lay = QtWidgets.QHBoxLayout(body)
      lay.setContentsMargins(0, 0, 0, 0)
      lay.setSpacing(0)
      lay.addWidget(self.nav)
      lay.addWidget(self.stack, 1)
      self.setCentralWidget(body)
      self._build_menu()
      ## Start page, shown until a project is open.
      self.start = StartPage(
         TITLE,
         "Open a game's project manifest (its reference/project.json) to edit its world, assets, scripts, "
         "battle data, build settings and code page in one window.",
         [("Open project...", lambda: self.open_game()), ("New game...", lambda: self.new_game())],
         "studio", lambda p: self.open_game(p),
         skip=("Continue without a project", lambda: self.show_editor()), recent_title="Recent projects")
      self.nav.currentRowChanged.connect(lambda row: self._show_row(row))
      self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
      self._update_title()
      self.nav.setCurrentRow(PAGES.index(page_by_id(page_id)) if page_id else 0)
      if path:
         self.open_game(path)

   @property
   def project_path(self) -> Path | None:
      """!The open project manifest's path.
      @return Path, or None before a project is open
      """
      return self._project_path

   @property
   def game_name(self) -> str | None:
      """!The open game's name (the Project page's, which may be edited).
      @return str, or None
      """
      return self._game_name

   def _set_game(self, path: Path | None, name: str | None) -> None:
      """!Records the open game.
      @param path  its project manifest
      @param name  its name, or None until the Project page gives it
      @return None
      """
      self._project_path = path
      self._game_name = name

   # -- pages -------------------------------------------------------------------

   def _placeholder(self, page: Page) -> QtWidgets.QLabel:
      """!What a page shows before it is built.
      @param page  Page
      @return QWidget
      """
      w = QtWidgets.QLabel(f"{page.title}: opening...")
      w.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
      return w

   def window_of(self, page_id: str) -> QtWidgets.QMainWindow:
      """!A page's tool window, built on first use.
      @param page_id  e.g. "world"
      @return QMainWindow
      """
      built = self.windows   # local names for "in": Doxygen 1.12 misreads "in self.x"
      if page_id in built:
         return built[page_id]
      page = page_by_id(page_id)
      index = PAGES.index(page)
      w = page.factory()
      w.setWindowFlags(QtCore.Qt.WindowType.Widget)   # a page, not a window of its own
      w.menuBar().setNativeMenuBar(False)
      w.menuBar().hide()   # its menus join the Studio's menu bar while it is in front
      for a in w.findChildren(QtGui.QAction):
         text = a.text().replace("&", "")
         if text == "Quit":   # the Studio quits, not a page
            a.setVisible(False)
            a.setShortcuts([])
         elif text == "Open project..." and page.page_id == "project":   # another game: the whole Studio opens it
            a.triggered.disconnect()
            a.triggered.connect(lambda _c=False: self.open_game())
            a.setToolTip("Open another game in the Studio (Studio > Open project...)")
      for a in w.menuBar().actions():   # one Record performance: the Studio's
         if a.menu() is not None and a.text().replace("&", "") == "Help":
            self._skipped_menus.add(a)
      w.windowTitleChanged.connect(lambda _t, pid=page_id: self._update_item(pid))
      if hasattr(w, "open_code_page"):   # the Battle page's Text page: the Project page's code page, not a window
         w.open_code_page = lambda: self.show_code_page()
      old = self.stack.widget(index)
      self.windows[page_id] = w
      self.stack.insertWidget(index, w)
      self.stack.removeWidget(old)
      old.deleteLater()
      if self.stack.currentIndex() != index:
         self._park(page_id)
      self._update_item(page_id)
      return w

   def reset_page(self, page_id: str) -> None:
      """!Closes a page's window (without asking: the caller asked first); it
      is built again, empty, the next time it is shown.
      @param page_id  page id
      @return None
      """
      w = self.windows.pop(page_id, None)
      if w is None:
         return
      self._parked.pop(page_id, None)
      self._stop_panels(w)
      page = page_by_id(page_id)
      index = PAGES.index(page)
      bar = self.menuBar()
      page_menus = self._page_menus   # local name for "in": Doxygen 1.12 misreads "in self.x"
      for a in w.menuBar().actions():
         if a in page_menus:
            bar.removeAction(a)
            page_menus.remove(a)
         self._skipped_menus.discard(a)
      placeholder = self._placeholder(page)
      self.stack.insertWidget(index, placeholder)
      self.stack.removeWidget(w)
      w.hide()
      w.deleteLater()
      self._update_item(page_id)

   def current_page_id(self) -> str:
      """!The page in front.
      @return page id
      """
      return PAGES[self.stack.currentIndex()].page_id

   def show_page(self, page_id: str) -> None:
      """!Brings a page to the front.
      @param page_id  e.g. "scripts"
      @return None
      """
      self.nav.setCurrentRow(PAGES.index(page_by_id(page_id)))

   def show_code_page(self) -> None:
      """!Brings the Project page to the front with its Code page panel.
      @return None
      """
      self.show_page("project")
      self.window_of("project").show_panel("codepage")

   def _show_row(self, row: int) -> None:
      """!The page list's selection changed.
      @param row  PAGES index
      @return None
      """
      if row < 0:
         return
      page = PAGES[row]
      previous = self.current_page_id() if self.stack.currentIndex() >= 0 else None
      w = self.window_of(page.page_id)
      self.stack.setCurrentIndex(row)
      built = self.windows
      for pid in built:   # every page but the one in front gives up its shortcuts
         if pid != page.page_id:
            self._park(pid)
      self._unpark(page.page_id)
      if previous is not None and previous != page.page_id and previous in built:
         self._stop_panels(built[previous])
      self._sync_menus(w)
      self._update_title()

   def _park(self, page_id: str) -> None:
      """!Takes a page's shortcuts away (it is not in front).
      @param page_id  page id
      @return None
      """
      parked = self._parked.setdefault(page_id, {})
      for a in self.windows[page_id].findChildren(QtGui.QAction):
         keys = a.shortcuts()
         if keys:
            parked[a] = keys
            a.setShortcuts([])

   def _unpark(self, page_id: str) -> None:
      """!Gives a page its shortcuts back (it is in front).
      @param page_id  page id
      @return None
      """
      for a, keys in self._parked.pop(page_id, {}).items():
         try:
            a.setShortcuts(keys)
         except RuntimeError:   # the action was deleted meanwhile
            pass

   def _stop_panels(self, window: QtWidgets.QMainWindow) -> None:
      """!Stops the panels of a page that went to the back (timers, previews).
      @param window  tool window
      @return None
      """
      for p in getattr(window, "panels", []):
         p.stop()

   def _sync_menus(self, window: QtWidgets.QMainWindow) -> None:
      """!Puts the page's menus after the Studio menu.
      @param window  tool window in front
      @return None
      """
      bar = self.menuBar()
      for a in self._page_menus:
         bar.removeAction(a)
      skipped = self._skipped_menus
      self._page_menus = [a for a in window.menuBar().actions() if a.menu() is not None and a not in skipped]
      for a in self._page_menus:
         bar.addAction(a)
      bar.removeAction(self.help_action)   # Help stays last
      bar.addAction(self.help_action)

   def _update_item(self, page_id: str) -> None:
      """!The page list shows whether a page has unsaved changes.
      @param page_id  page id
      @return None
      """
      page = page_by_id(page_id)
      item = self.nav.item(PAGES.index(page))
      w = self.windows.get(page_id)
      title = w.windowTitle() if w is not None else ""
      name = title.split(" - ")[0]   # titles read "file * - Tool": the file part ends with " *" when unsaved
      item.setText(page.title + (" *" if name.endswith(" *") else ""))
      path = page.opened(w) if w is not None else None
      if path is not None and self._project_path is not None:
         try:
            path = path.relative_to(self._project_path.parent.parent)
         except ValueError:   # a file outside the game (opened from the page's File menu)
            pass
      item.setToolTip(str(path) if path is not None else "nothing open")
      if page_id == "project":
         self._update_title()   # the game's name may have changed

   # -- the Studio menu ---------------------------------------------------------

   def _build_menu(self) -> None:
      """!The Studio menu: open a project, go to a page, quit.
      @return None
      """
      keys = QtGui.QKeySequence.StandardKey
      ## The Studio menu.
      self.studio_menu = self.menuBar().addMenu("S&tudio")
      a = QtGui.QAction("&Open project...", self)
      a.triggered.connect(lambda _c=False: self.open_game())
      self.studio_menu.addAction(a)
      a = QtGui.QAction("&New game...", self)
      a.setToolTip("A new game folder from a battle data template (Blank, Starter, ...)")
      a.triggered.connect(lambda _c=False: self.new_game())
      self.studio_menu.addAction(a)
      # S5: any JSON file read-only (an imported game's importer / tier-3 data the studio has no editor for)
      a = QtGui.QAction("Open data file (read-&only)...", self)
      a.setToolTip("Show a JSON file as a tree without editing it (e.g. world/scripts/story.json, ui/menus.json)")
      a.triggered.connect(lambda _c=False: json_view.show_read_only())
      self.studio_menu.addAction(a)
      self.studio_menu.addSeparator()
      for i, p in enumerate(PAGES):
         a = QtGui.QAction(f"Go to {p.title}", self)
         a.setShortcut(QtGui.QKeySequence(f"Ctrl+{i + 1}"))
         a.triggered.connect(lambda _c=False, pid=p.page_id: self.show_page(pid))
         self.studio_menu.addAction(a)
      self.studio_menu.addSeparator()
      a = QtGui.QAction("&Quit", self)
      a.setShortcuts(keys.Quit)
      a.triggered.connect(lambda _c=False: self.close())
      self.studio_menu.addAction(a)
      ## Help > Record performance, for the whole Studio (the pages' own are left out).
      self.recorder = profiler.add_menu(self, "studio")
      ## The Help menu's action in the menu bar (kept last).
      self.help_action = self.menuBar().actions()[-1]

   def profile_notes(self) -> list[str]:
      """!What the performance report should know: the pages built and what they have open.
      @return list of lines
      """
      notes = [f"studio: page in front {self.current_page_id()}; game {self._project_path or 'none'}"]
      for pid, w in list(self.windows.items()):
         notes.append(f"page {pid}: {page_by_id(pid).opened(w) or 'nothing open'}")
         extra = getattr(w, "profile_notes", None)
         if callable(extra):
            notes.extend(f"  {line}" for line in extra())
      return notes

   def show_status(self, text: str) -> None:
      """!Shows a message in the status bar of the page in front.
      @param text  message
      @return None
      """
      w = self.windows.get(self.current_page_id())
      if w is not None and hasattr(w, "show_status"):
         w.show_status(text)

   # -- opening a game ----------------------------------------------------------

   def dialog_parent(self) -> QtWidgets.QWidget:
      """!Window dialogs belong to: the start window while it is the one shown.
      @return QWidget
      """
      return self.start if self.start.isVisible() else self

   def show_editor(self) -> None:
      """!Shows the Studio (with or without a project) instead of the start window.
      @return None
      """
      self.start.hide()
      self.show()

   def launch(self) -> None:
      """!Shows the Studio when a project is open, else the start window.
      @return None
      """
      if self._project_path is not None:
         self.show()
      else:
         self.start.refresh()
         self.start.show()

   def _confirm_all(self) -> bool:
      """!Asks every built page about its unsaved changes.
      @return True to go ahead
      """
      for pid, w in list(self.windows.items()):
         confirm = getattr(w, "_confirm_discard", None)
         if confirm is None:
            continue
         if w.windowTitle().split(" - ")[0].endswith(" *"):
            self.show_page(pid)   # it asks about what you can see
         if not confirm():
            self.show_page(pid)
            return False
      return True

   def new_game(self, template: str | None = None, folder: str | Path | None = None, name: str | None = None) -> bool:
      """!A new game from a template (ui/new_dialog.py NewDialog: its data in data/, reference/project.json), then
      opened. With a template and a folder nothing is asked (tests, scripts).
      @param template  template id, or None to ask
      @param folder    the new game's folder, or None to ask
      @param name      the game's name, or None (the folder's)
      @return True when the game was made and opened
      """
      from .new_dialog import GAME, NewDialog   # local: only this action needs it

      dialog = NewDialog(GAME, folder, None, self.dialog_parent())
      if name:
         dialog.name.setText(name)
      if template is not None and folder is not None:
         if not dialog.select(template) or dialog.create() is None:
            report_failure(self, "New game", dialog.message.text() or f"no template {template!r}")
            return False
      elif dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted or dialog.created is None:
         return False
      return self.open_game(dialog.created)

   def open_game(self, path: str | Path | None = None) -> bool:
      """!Opens a game: each file its project manifest names, on its page.
      @param path  reference/project.json, or None to ask
      @return True when the project opened
      """
      if path is None:
         path, _ = QtWidgets.QFileDialog.getOpenFileName(self.dialog_parent(), "Open project", "", PROJECT_FILTER)
         if not path:
            return False
      try:
         doc = project_core.open_project(path)
         files = project_core.game_files(doc)
      except DocumentError as e:
         QtWidgets.QMessageBox.warning(self.dialog_parent(), "Open project", f"{path}: {e}")
         return False
      if not self._confirm_all():
         return False
      problems = []
      for key, file in files.items():
         if not file.is_file():
            problems.append(f"{key}: {file} does not exist")
      front = self.stack.currentIndex()
      self._set_game(doc.path, None)
      for page in PAGES:
         target = doc.path if page.file_key == "project" else files.get(page.file_key)
         if target is None or not Path(target).is_file():
            self.reset_page(page.page_id)   # nothing of the old game stays open
            continue
         w = self.window_of(page.page_id)
         w._confirm_discard = lambda: True   # asked above, for every page at once
         error = None
         try:
            getattr(w, page.opener)(str(target))
         except Exception as e:   # a tool that raises on a malformed file must not take the Studio down
            traceback.print_exc()
            error = e
         finally:
            del w._confirm_discard   # the window's own method again
         opened = page.opened(w)
         if error is not None or opened is None or Path(opened).resolve() != Path(target).resolve():
            why = f" ({type(error).__name__}: {error})" if error is not None else ""
            problems.append(f"{page.title}: {target} did not open{why}")   # failed or cancelled
            self.reset_page(page.page_id)
      for i in range(self.stack.count()):   # a tool may show itself when it opens a file
         self.stack.widget(i).setVisible(i == front)
      self.stack.setCurrentIndex(front)
      remember_file("studio", doc.path)
      self.start.hide()
      if not self.isVisible():
         self.show()
      first = next((p.page_id for p in PAGES if p.page_id in self.windows), "project")
      self.show_page(first)
      self._show_row(PAGES.index(page_by_id(first)))   # also when that page was already in front
      built = self.windows
      for pid in built:
         self._update_item(pid)
      if problems:
         QtWidgets.QMessageBox.warning(self, "Open project", "Some of the game's files are not open:\n\n"
                                       + "\n".join(problems))
      return True

   def _update_title(self) -> None:
      """!Window title: the game's name and the page in front.
      @return None
      """
      page = PAGES[self.stack.currentIndex()].title if self.stack.currentIndex() >= 0 else ""
      pw = self.windows.get("project")
      doc = getattr(pw, "document", None) if pw is not None else None
      if doc is not None and doc.path is not None:   # the Project page's game (its name may be edited)
         self._set_game(self._project_path, doc.data.get("name") or doc.path.parent.parent.name)
      game = f"{self._game_name} - " if self._game_name else ""
      self.setWindowTitle(f"{game}{page} - {TITLE}" if page else TITLE)

   def closeEvent(self, event: QtGui.QCloseEvent) -> None:
      """!Asks every page about unsaved changes before closing.
      @param event  QCloseEvent
      @return None
      """
      if self._confirm_all():
         for w in self.windows.values():
            self._stop_panels(w)
         if self.recorder.recording():   # keep the report
            print(f"studio: performance report saved: {self.recorder.stop()}", file=sys.stderr)
         event.accept()
      else:
         event.ignore()
