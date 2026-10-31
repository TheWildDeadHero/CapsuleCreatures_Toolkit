"""!The Open a sample... dialog (D-40 RP): pick one of the engine's sample projects (core.samples.discover(): the
Starter Battle, the Map Sandbox), see what it shows, choose a new folder and a name, and copy it there as a game of
your own (core.samples.copy(): its files, the engine data it shares, build-safe name and ROM header).

The Studio opens the copy afterwards (ui/studio_shell.py open_sample()). Nothing is overwritten, and the copy never
goes into the engine or the Studio's own files. copy_sample() does the work, so tests and headless runs fill the
fields and call it without showing the dialog.
"""
from __future__ import annotations

import html
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from ..core import samples
from ..core.document import DocumentError
from .widgets import button

## Dialog title.
TITLE = "Open a sample"
## Item data role of a sample row: its index in SampleDialog.samples.
SAMPLE_ROLE = QtCore.Qt.ItemDataRole.UserRole
## Width of the dialog when it opens, pixels.
DIALOG_WIDTH = 720
## Height of the dialog when it opens, pixels.
DIALOG_HEIGHT = 420
## Stretch of the sample list beside the description.
LIST_STRETCH = 1
## Stretch of the description beside the sample list.
TEXT_STRETCH = 2
## Text colour of discovery problems and refusals.
ERROR_COLOR = "#c03030"
## What the description adds under each sample: what a copy is.
COPY_TEXT = ("The copy is a game of your own in the folder below: the sample's files, its own copy of the engine "
             "data it uses (data/starter) and a build-safe name. Build it with ./build gba-release --game FOLDER.")


class SampleDialog(QtWidgets.QDialog):
   """!Sample list (each with its one line), description, target folder and name; copy_sample() makes the copy.

   @var samples
   The samples found (core.samples.Sample), in list order.
   @var created
   The copy's project manifest after copy_sample() worked, or None.
   """

   def __init__(self, folder: str | Path | None = None, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the dialog.
      @param folder  the target folder to start with, or None
      @param parent  parent widget
      """
      super().__init__(parent)
      self.created = None
      self.setWindowTitle(TITLE)
      self.resize(DIALOG_WIDTH, DIALOG_HEIGHT)
      found, problems = samples.discover()
      self.samples = found
      ## The samples, one row each: the name and its one line.
      self.sample_list = QtWidgets.QListWidget()
      self.sample_list.setWordWrap(True)
      for i, s in enumerate(found):
         item = QtWidgets.QListWidgetItem(f"{s.name}\n{s.description}")
         item.setData(SAMPLE_ROLE, i)
         item.setToolTip(str(s.folder))
         self.sample_list.addItem(item)
      self.sample_list.currentRowChanged.connect(lambda _row: self._show_sample())
      ## The chosen sample's description and what its copy gets.
      self.description = QtWidgets.QLabel()
      self.description.setWordWrap(True)
      self.description.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft)
      self.description.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
      ## The new game's folder (new, or empty).
      self.folder = QtWidgets.QLineEdit(str(folder) if folder is not None else "")
      self.folder.setPlaceholderText("the new game's folder (new or empty), e.g. in your home folder")
      ## The game's name (default the folder's name).
      self.name = QtWidgets.QLineEdit()
      self.name.setPlaceholderText("default: the folder's name")
      ## Discovery problems and the last refusal.
      self.message = QtWidgets.QLabel("\n".join(problems))
      self.message.setWordWrap(True)
      self.message.setStyleSheet(f"color: {ERROR_COLOR};")
      self.message.setVisible(bool(problems))

      top = QtWidgets.QHBoxLayout()
      top.addWidget(self.sample_list, LIST_STRETCH)
      top.addWidget(self.description, TEXT_STRETCH)
      form = QtWidgets.QFormLayout()
      where = QtWidgets.QHBoxLayout()
      where.addWidget(self.folder, 1)
      where.addWidget(button("Browse...", lambda: self.browse(), "Pick the new game's folder"))
      form.addRow("Folder", where)
      form.addRow("Name", self.name)
      buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
      ## The Copy and open button.
      self.copy_button = buttons.addButton("Copy and open", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
      buttons.accepted.connect(lambda: self._copy_and_close())
      buttons.rejected.connect(lambda: self.reject())
      lay = QtWidgets.QVBoxLayout(self)
      lay.addLayout(top, 1)
      lay.addLayout(form)
      lay.addWidget(self.message)
      lay.addWidget(buttons)
      if found:
         self.sample_list.setCurrentRow(0)
      self._show_sample()

   # -- choices -------------------------------------------------------------------------------------------------------

   def sample(self) -> samples.Sample | None:
      """!The chosen sample.
      @return Sample, or None when none is found
      """
      row = self.sample_list.currentRow()
      return self.samples[row] if 0 <= row < len(self.samples) else None

   def select(self, sample_id: str) -> bool:
      """!Chooses a sample.
      @param sample_id  its id
      @return True when the list has it
      """
      ids = [s.id for s in self.samples]
      if sample_id not in ids:
         return False
      self.sample_list.setCurrentRow(ids.index(sample_id))
      return True

   def _show_sample(self) -> None:
      """!Shows the chosen sample's description.
      @return None
      """
      s = self.sample()
      if s is None:
         self.description.setText("No sample projects found in the engine.")
         self.copy_button.setEnabled(False)
         return
      shared = ", ".join(share.to for share in s.shared)
      lines = [f"<b>{html.escape(s.name)}</b> &middot; {html.escape(s.id)}, version {s.version}",
               html.escape(s.description), html.escape(COPY_TEXT)]
      if shared:
         lines.append(f"<i>engine data copied along</i>: {html.escape(shared)}")
      self.description.setText("<br><br>".join(lines))
      self.copy_button.setEnabled(True)

   def browse(self) -> None:
      """!Picks the new game's folder.
      @return None
      """
      folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Folder for the copy", self.folder.text())
      if folder:
         self.folder.setText(folder)

   # -- copying -------------------------------------------------------------------------------------------------------

   def copy_sample(self) -> Path | None:
      """!Copies the chosen sample into the folder; a refusal shows in the dialog.
      @return the copy's project manifest, or None when refused
      """
      s = self.sample()
      folder = self.folder.text().strip()
      try:
         if s is None:
            raise DocumentError("no sample is chosen")
         if not folder:
            raise DocumentError("name the new game's folder")
         self.created = samples.copy(s, Path(folder), self.name.text().strip() or None)
      except (DocumentError, OSError) as e:
         self.message.setText(str(e))
         self.message.setVisible(True)
         return None
      return self.created

   def _copy_and_close(self) -> None:
      """!Copy and open: closes the dialog when it worked.
      @return None
      """
      if self.copy_sample() is not None:
         self.accept()
