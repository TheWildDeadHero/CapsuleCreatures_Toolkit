"""![S7] The audio editor's window: a PanelHost for a game's audio manifest (capsule.audio/1, engine M4 / D-34).

Its tabs are the audio panels (AUDIO_PANELS): Songs (the song player and viewer), Instruments (voices, envelopes,
key splits, drum sets, bank windows), Samples (WAV import, waveforms), MIDI import and Sound effects (the song
table, players, priorities, two sounds at once). The Problems list under them shows what the engine's
tools/audio/format.py finds in the manifest (unsaved edits included), refreshed after every change; every edit is
also checked before it becomes an undo step, so a change the build would refuse is refused with its reason.

The window owns the File (new, open, save, save as), Edit (undo, redo) and Audio menus (check, build the
renderer, show the render folder) and the status bar. It runs alone (audio-editor) and as the Studio's Audio
page (a game's project.json names its manifest under "audio", as the engine's capsule_audio_game() reads it).
"""
from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtGui, QtWidgets

from ..core import audio, audio_render as ar, bench, engine
from ..core.document import DocumentError
from . import background, profiler
from .editors.audio_common import open_externally
from .editors.audio_instruments import InstrumentPanel
from .editors.audio_midi import MidiPanel
from .editors.audio_samples import SamplePanel
from .editors.audio_songs import SongPanel
from .editors.audio_sounds import SoundPanel
from .panes import NARROW, WIDE, fit_panel, splitter
from .widgets import STATUS_MS, Debounce, StartPage, file_toolbar, remember_file, report_failure

if TYPE_CHECKING:
   from ..core.document import Document
   from .panel import EditorPanel

## The audio panels, in tab order.
AUDIO_PANELS = [SongPanel, InstrumentPanel, SamplePanel, MidiPanel, SoundPanel]
## File dialog filter.
AUDIO_FILTER = "Audio manifest (audio.json *.json);;All files (*)"
## Tool name (recent files, settings).
TOOL = "audio-editor"
## Window title.
TITLE = "CapsuleCreatures Audio Editor"
## Width and height of the window when it opens, pixels.
WINDOW_WIDTH, WINDOW_HEIGHT = 1400, 860
## Starting height of the problems list, pixels (the user drags its boundary).
PROBLEMS_HEIGHT = 64


class AudioWindow(QtWidgets.QMainWindow):
   """!Main window hosting the audio panels (implements PanelHost, see panel.py)."""

   def __init__(self, path: str | Path | None = None) -> None:
      """!Creates the window.
      @param path  an audio manifest to open, or None
      """
      super().__init__()
      ## The open AudioDocument, or None.
      self.document = None
      ## Unused by the audio panels; present for the PanelHost contract.
      self.reports = None
      ## The renderer of the open manifest (made on first use).
      self._renderer = None
      ## The hosted panels.
      self.panels = []
      ## The latest problems format.py found.
      self.problems = []
      self._build_menus()
      ## The tab widget.
      self.tabs = QtWidgets.QTabWidget()
      for cls in AUDIO_PANELS:
         panel = cls(self)
         fit_panel(panel)   # [RZ] scroll bars instead of a window larger than the screen
         self.panels.append(panel)
         self.tabs.addTab(panel, panel.title)
      self.tabs.currentChanged.connect(lambda _i: self._tab_changed())
      ## The problems list.
      self.problem_list = QtWidgets.QListWidget()
      self.problem_list.setToolTip("What the engine's format.py finds in the manifest (the build refuses these)")
      # [RZ] the panels above, the problems below: drag the boundary (the list starts PROBLEMS_HEIGHT high)
      ## The panels | problems splitter.
      self.split = splitter(QtCore.Qt.Orientation.Vertical, [self.tabs, self.problem_list], [WIDE, NARROW],
                            [None, PROBLEMS_HEIGHT])
      self.setCentralWidget(self.split)
      ## Revalidates once edits pause.
      self._check_later = Debounce(lambda: self.check(), parent=self)
      ## Start page, shown until a manifest is open.
      self.start = StartPage(
         TITLE, "Open a game's audio manifest (audio.json, capsule.audio/1) to play its songs, edit its "
                "instruments and samples, import WAV and MIDI files and test its sound effects.",
         [("Open audio manifest...", lambda: self.open_file()), ("New audio manifest...", lambda: self.new_file())],
         TOOL, lambda p: self.open_file(p), skip=("Continue without a manifest", lambda: self.show_editor()),
         recent_title="Recent audio manifests")
      self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
      self._update_title()
      if path:
         self.open_file(path)

   # -- PanelHost ----------------------------------------------------------------------------------------------

   def show_status(self, text: str) -> None:
      """!Shows a message in the status bar.
      @param text  message
      @return None
      """
      self.statusBar().showMessage(text, STATUS_MS)

   def apply(self, label: str, fn: Callable[[], object]) -> bool:
      """!Runs a core edit (core.audio makes its own checked undo step); a refused edit becomes a message.
      @param label  what the change is called
      @param fn     callable without arguments
      @return True when it went through
      """
      if self.document is None:
         return False
      try:
         fn()
      except (DocumentError, OSError, ValueError, engine.EngineNotFound) as e:
         report_failure(self, label, str(e))
         self.refresh()   # put the widgets back
         return False
      self.refresh()
      return True

   def run_edit(self, label: str, fn: Callable[[], object], document: Document | None = None) -> bool:
      """!Runs fn() inside document.edit(label) (PanelHost contract).
      @param label     undo label
      @param fn        callable
      @param document  Document to edit (default: the manifest)
      @return True when the edit went through
      """
      doc = document or self.document
      if doc is None:
         return False

      def edit() -> None:
         """!The edit block."""
         with doc.edit(label):
            fn()
      return self.apply(label, edit)

   def selection_changed(self) -> None:
      """!Update the title and menus.
      @return None
      """
      self._update_title()

   def renderer(self) -> ar.Renderer:
      """!The open manifest's renderer (core.audio_render; its cache folder follows the manifest).
      @return Renderer
      @throws DocumentError without a manifest
      """
      if self.document is None:
         raise DocumentError("no audio manifest is open")
      if self._renderer is None or self._renderer.doc is not self.document:
         self._renderer = ar.Renderer(self.document)
      return self._renderer

   def show_panel(self, panel_id: str) -> EditorPanel:
      """!Brings a panel's tab to the front.
      @param panel_id  e.g. "audio_songs"
      @return the panel
      @throws KeyError when there is none
      """
      found = [p for p in self.panels if p.panel_id == panel_id]
      if not found:
         raise KeyError(panel_id)
      self.tabs.setCurrentWidget(found[0])
      return found[0]

   def _tab_changed(self) -> None:
      """!Another tab is in front: the others stop.
      @return None
      """
      for p in self.panels:
         if p is not self.tabs.currentWidget():
            p.stop()
      self._update_title()

   def refresh(self) -> None:
      """!Refreshes every panel, the title and the menus; the problems follow once edits pause.
      @return None
      """
      for p in self.panels:
         p.refresh()
      self._update_title()
      self._check_later.poke()

   # -- checks ---------------------------------------------------------------------------------------------------

   def check(self, wait: bool = False) -> list[str]:
      """!Validates the manifest with format.py on a worker thread (a copy of it) and lists the problems.
      @param wait  True: on this thread, now (tests, the Audio menu)
      @return the problems when wait, else the previous ones
      """
      if self.document is None:
         self._show_problems([])
         return []
      data, base = self.document.view()
      snapshot = copy.deepcopy(data)
      if wait:
         self._show_problems(audio.fmt().validate(snapshot, base))
         return self.problems

      def work() -> Any:
         """!The check.
         @return problems or the exception
         """
         try:
            return audio.fmt().validate(snapshot, base)
         except (OSError, ValueError) as e:
            return [f"check failed: {e}"]
      background.start(self, "check", work, lambda problems: self._show_problems(problems))
      return self.problems

   def _show_problems(self, problems: list[str]) -> None:
      """!Fills the problems list.
      @param problems  the problems
      @return None
      """
      self.problems = list(problems)
      self.problem_list.clear()
      if not problems:
         self.problem_list.addItem("No problems (format.py): the build's audio compiler takes this manifest")
      for p in problems:
         self.problem_list.addItem(p)

   # -- window ---------------------------------------------------------------------------------------------------

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
      """!File, Edit and Audio menus and the toolbar.
      @return None
      """
      keys = QtGui.QKeySequence.StandardKey
      m = self.menuBar().addMenu("&File")
      ## New manifest.
      self.new_action = self._action(m, "&New audio manifest...", lambda: self.new_file(), keys.New)
      ## Open a manifest.
      self.open_action = self._action(m, "&Open audio manifest...", lambda: self.open_file(), keys.Open)
      ## Save.
      self.save_action = self._action(m, "&Save", lambda: self.save(), keys.Save)
      ## Save as.
      self.save_as_action = self._action(m, "Save &as...", lambda: self.save_as(), keys.SaveAs)
      m.addSeparator()
      self._action(m, "&Quit", lambda: self.close(), keys.Quit)
      m = self.menuBar().addMenu("&Edit")
      ## Undo.
      self.undo_action = self._action(m, "Undo", lambda: self._undo_redo(True), keys.Undo)
      ## Redo.
      self.redo_action = self._action(m, "Redo", lambda: self._undo_redo(False), keys.Redo)
      m = self.menuBar().addMenu("&Audio")
      ## Check the manifest now.
      self.check_action = self._action(m, "&Check manifest", lambda: self._check_now())
      ## Build the renderer.
      self.build_action = self._action(m, "&Build the renderer", lambda: self.build_renderer())
      ## Show the render folder.
      self._action(m, "Show the &render folder", lambda: self.show_render_folder())
      ## Help > Record performance.
      self.recorder = profiler.add_menu(self, TOOL)
      ## Toolbar.
      self.file_bar = file_toolbar(self, [
         ("open", self.open_action, "Open a game's audio manifest", "Open"),
         ("save", self.save_action, "Save the manifest and the files imported into it"),
         None,
         ("undo", self.undo_action, "Undo"),
         ("redo", self.redo_action, "Redo"),
         None,
         ("check", self.check_action, "Check the manifest with the engine's format.py", "Check")])

   def _check_now(self) -> None:
      """!Audio > Check manifest.
      @return None
      """
      problems = self.check(wait=True)
      self.show_status(f"{len(problems)} problems" if problems else "No problems")

   def build_renderer(self) -> None:
      """!Audio > Build the renderer (the preview program, on a worker thread).
      @return None
      """
      if self.document is None:
         return
      r = self.renderer()
      missing = ar.toolchain()
      if missing:
         report_failure(self, "Build the renderer", "; ".join(missing))
         return

      def work() -> Any:
         """!The build.
         @return the program or the exception
         """
         try:
            return r.build(ar.PREVIEW_TARGET)
         except (audio.AudioError, bench.BenchError, OSError) as e:
            return e

      self.show_status("Building the renderer...")
      background.start(self, "build", work, lambda res: self.show_status(
         f"Built {res}" if isinstance(res, Path) else f"Build failed: {res}"))

   def show_render_folder(self) -> None:
      """!Audio > Show the render folder.
      @return None
      """
      if self.document is None:
         return
      folder = self.renderer().folder
      if not open_externally(folder):
         self.show_status(f"Render folder: {folder}")

   def _undo_redo(self, undo: bool) -> None:
      """!Undo or Redo.
      @param undo  True for undo
      @return None
      """
      doc = self.document
      if doc is None:
         return
      if doc.undo() if undo else doc.redo():
         self.refresh()

   def _update_title(self) -> None:
      """!Title and enabled actions.
      @return None
      """
      doc = self.document
      if doc is None:
         self.setWindowTitle(TITLE)
      else:
         name = doc.path.name if doc.path else "untitled"
         self.setWindowTitle(f"{name}{' *' if doc.dirty else ''} - {TITLE}")
      self.save_action.setEnabled(doc is not None and doc.dirty)
      undo = doc.undo_label() if doc is not None else None
      redo = doc.redo_label() if doc is not None else None
      self.undo_action.setEnabled(undo is not None)
      self.undo_action.setText(f"Undo {undo}" if undo else "Undo")
      self.redo_action.setEnabled(redo is not None)
      self.redo_action.setText(f"Redo {redo}" if redo else "Redo")

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
      if self.document is None:
         self.show_status("No audio manifest open: File > Open audio manifest...")

   def launch(self) -> None:
      """!Shows the editor when something is open, else the start window.
      @return None
      """
      if self.document is not None:
         self.show()
      else:
         self.start.refresh()
         self.start.show()

   # -- files ----------------------------------------------------------------------------------------------------

   def _confirm_discard(self) -> bool:
      """!Asks about unsaved changes.
      @return True to go ahead
      """
      for p in self.panels:
         p.commit()
      if self.document is None or not self.document.dirty:
         return True
      b = QtWidgets.QMessageBox.StandardButton
      answer = QtWidgets.QMessageBox.question(self.dialog_parent(), "Unsaved changes", "Save changes first?",
                                              b.Save | b.Discard | b.Cancel, b.Save)
      if answer == b.Save:
         return self.save()
      return answer == b.Discard

   def set_document(self, doc: audio.AudioDocument) -> None:
      """!Shows a document.
      @param doc  AudioDocument
      @return None
      """
      self.document = doc
      self._renderer = None
      for p in self.panels:
         p.document_replaced()
      self.start.hide()
      self.show()
      self._update_title()
      self.check()

   def open_file(self, path: str | Path | None = None) -> None:
      """!Opens an audio manifest.
      @param path  audio.json, or None to ask
      @return None
      """
      if not self._confirm_discard():
         return
      if path is None:
         path, _ = QtWidgets.QFileDialog.getOpenFileName(self.dialog_parent(), "Open audio manifest", "",
                                                         AUDIO_FILTER)
         if not path:
            return
      try:
         doc = audio.open_audio(path)
      except DocumentError as e:
         report_failure(self.dialog_parent(), "Open audio manifest", str(e))
         return
      remember_file(TOOL, Path(path))
      self.set_document(doc)

   def new_file(self, path: str | Path | None = None) -> None:
      """!Starts a new manifest (saved at once so imports have a folder).
      @param path  where, or None to ask
      @return None
      """
      if not self._confirm_discard():
         return
      if path is None:
         path, _ = QtWidgets.QFileDialog.getSaveFileName(self.dialog_parent(), "New audio manifest", "audio.json",
                                                         AUDIO_FILTER)
         if not path:
            return
      doc = audio.new_audio(path)
      doc.save()
      remember_file(TOOL, Path(path))
      self.set_document(doc)

   def save(self) -> bool:
      """!Saves the manifest and the files imported into it.
      @return True when saved (or nothing to save)
      """
      for p in self.panels:
         p.commit()
      doc = self.document
      if doc is None or not doc.dirty:
         return True
      if doc.path is None:
         return self.save_as()
      try:
         doc.save()
      except (OSError, DocumentError) as e:
         report_failure(self, "Save", str(e))
         return False
      self.show_status(f"Saved {doc.path.name}")
      self.refresh()
      return True

   def save_as(self, path: str | Path | None = None) -> bool:
      """!Saves under another name (the data files go beside it).
      @param path  the new file, or None to ask
      @return True when saved
      """
      doc = self.document
      if doc is None:
         return False
      if path is None:
         path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save audio manifest as", "audio.json", AUDIO_FILTER)
         if not path:
            return False
      try:
         doc.save(path)
      except (OSError, DocumentError) as e:
         report_failure(self, "Save as", str(e))
         return False
      self._renderer = None
      remember_file(TOOL, Path(path))
      self.refresh()
      return True

   def closeEvent(self, event: QtGui.QCloseEvent) -> None:
      """!Asks about unsaved changes before closing.
      @param event  QCloseEvent
      @return None
      """
      if self._confirm_discard():
         for p in self.panels:
            p.stop()
         event.accept()
      else:
         event.ignore()
