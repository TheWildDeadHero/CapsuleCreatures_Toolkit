"""!The New game / New battle data dialog (D-23 section 3.5, S10): pick a
battle data template (core.templates.discover(): the built-in Blank, the
engine's samples such as Starter, the reference repo's and the plugins'),
see what it gives, and create:

  - a game (GAME mode, the Studio's Studio > New game...): a new folder with
    the template's files in data/ and reference/project.json naming the
    battle and asset manifests (core.templates.new_game());
  - battle data (BATTLE mode, the battle editor's File > New battle
    data...): the template's files, or only some of its parts, copied into a
    folder with their relative paths (core.templates.apply()).

Nothing is overwritten. create() does the work, so tests and headless runs
fill the fields and call it without showing the dialog.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

from ..core import templates
from ..core.document import DocumentError
from .widgets import button

if TYPE_CHECKING:
   from ..plugins.registry import Registry

## Mode: a new game folder.
GAME = "game"
## Mode: battle data in a folder.
BATTLE = "battle"
## Dialog titles by mode.
TITLES = {GAME: "New game", BATTLE: "New battle data"}
## Item data role of a template row: its index in NewDialog.templates.
TEMPLATE_ROLE = QtCore.Qt.ItemDataRole.UserRole
## Width of the dialog when it opens, pixels.
DIALOG_WIDTH = 720
## Height of the dialog when it opens, pixels.
DIALOG_HEIGHT = 460
## Stretch of the template list beside the description.
LIST_STRETCH = 1
## Stretch of the description beside the template list.
TEXT_STRETCH = 2
## Text colour of discovery problems and refusals.
ERROR_COLOR = "#c03030"
## The template a dialog selects first.
FIRST_CHOICE = "starter"
## The battle manifest a folder of battle data opens by (when only some parts were copied into it).
BATTLE_FILE = "battle.json"


def template_registry(project: str | Path | None = None) -> Registry:
   """!The plugins whose battle templates count: the studio's own, plus a game's project plugins.
   @param project  the game's reference/project.json, or None
   @return plugins.Registry
   """
   from ..plugins import loader, project as proj

   reg = loader.builtin_registry()
   if project is not None and Path(project).is_file():
      reg = reg.copy()
      path = Path(project).resolve()
      try:
         loader.load_folders(reg, proj.plugin_folders(path, path.parent.parent))
      except (OSError, ValueError) as e:
         reg.errors.append((str(path), str(e)))
   return reg


class NewDialog(QtWidgets.QDialog):
   """!Template list, description, parts, target folder; create() makes the game or the battle data.

   @var mode
   GAME or BATTLE.
   @var templates
   The templates found (core.templates.Template), in list order.
   @var created
   What create() made last (the project manifest or the battle manifest), or None.
   """

   def __init__(self, mode: str = GAME, folder: str | Path | None = None, registry: Registry | None = None,
                parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the dialog.
      @param mode      GAME or BATTLE
      @param folder    the target folder to start with, or None
      @param registry  plugins.Registry whose templates count (template_registry()), or None for the studio's own
      @param parent    parent widget
      """
      super().__init__(parent)
      if mode not in TITLES:
         raise ValueError(f"unknown mode {mode!r} ({', '.join(TITLES)})")
      self.mode = mode
      self.created = None
      self.setWindowTitle(TITLES[mode])
      self.resize(DIALOG_WIDTH, DIALOG_HEIGHT)
      found, problems = templates.discover(registry if registry is not None else template_registry())
      self.templates = found
      ## The templates, one row each.
      self.template_list = QtWidgets.QListWidget()
      for i, t in enumerate(found):
         item = QtWidgets.QListWidgetItem(t.label())
         item.setData(TEMPLATE_ROLE, i)
         item.setToolTip(str(t.folder))
         self.template_list.addItem(item)
      self.template_list.currentRowChanged.connect(lambda _row: self._show_template())
      ## The chosen template's description and files.
      self.description = QtWidgets.QLabel()
      self.description.setWordWrap(True)
      self.description.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft)
      self.description.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
      ## One check box per part (BATTLE mode: copy only some parts; a game gets every part).
      self.part_boxes = {}
      parts_row = QtWidgets.QHBoxLayout()
      parts_row.addWidget(QtWidgets.QLabel("Parts"))
      for part in templates.PARTS:
         box = QtWidgets.QCheckBox(part.capitalize())
         box.setChecked(True)
         box.setEnabled(mode == BATTLE)
         self.part_boxes[part] = box
         parts_row.addWidget(box)
      parts_row.addStretch(1)
      ## Target folder (a game: the new game's folder; battle data: where the files go).
      self.folder = QtWidgets.QLineEdit(str(folder) if folder is not None else "")
      self.folder.setPlaceholderText("the new game's folder (new or empty)" if mode == GAME
                                     else "the folder the battle data goes in")
      ## The game's name (GAME mode; default the folder's name).
      self.name = QtWidgets.QLineEdit()
      self.name.setPlaceholderText("default: the folder's name")
      ## Discovery problems and the last refusal.
      self.message = QtWidgets.QLabel("\n".join(problems))
      self.message.setWordWrap(True)
      self.message.setStyleSheet(f"color: {ERROR_COLOR};")
      self.message.setVisible(bool(problems))

      top = QtWidgets.QHBoxLayout()
      top.addWidget(self.template_list, LIST_STRETCH)
      top.addWidget(self.description, TEXT_STRETCH)
      form = QtWidgets.QFormLayout()
      where = QtWidgets.QHBoxLayout()
      where.addWidget(self.folder, 1)
      where.addWidget(button("Browse...", lambda: self.browse(), "Pick the folder"))
      form.addRow("Folder", where)
      if mode == GAME:
         form.addRow("Name", self.name)
      buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
      ## The Create button.
      self.create_button = buttons.addButton("Create", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
      buttons.accepted.connect(lambda: self._create_and_close())
      buttons.rejected.connect(lambda: self.reject())
      lay = QtWidgets.QVBoxLayout(self)
      lay.addLayout(top, 1)
      lay.addLayout(parts_row)
      lay.addLayout(form)
      lay.addWidget(self.message)
      lay.addWidget(buttons)
      ids = [t.id for t in found]
      self.template_list.setCurrentRow(ids.index(FIRST_CHOICE) if FIRST_CHOICE in ids else 0)
      self._show_template()

   # -- choices -------------------------------------------------------------------------------------------------------

   def template(self) -> templates.Template | None:
      """!The chosen template.
      @return Template, or None when none is found
      """
      row = self.template_list.currentRow()
      return self.templates[row] if 0 <= row < len(self.templates) else None

   def select(self, template_id: str) -> bool:
      """!Chooses a template.
      @param template_id  its id
      @return True when the list has it
      """
      ids = [t.id for t in self.templates]
      if template_id not in ids:
         return False
      self.template_list.setCurrentRow(ids.index(template_id))
      return True

   def parts(self) -> list[str]:
      """!The parts to copy: every part of the template for a game, the ticked ones it gives for battle data.
      @return part names
      """
      t = self.template()
      given = list(t.parts) if t is not None else []
      if self.mode == GAME:
         return given
      return [p for p in given if self.part_boxes[p].isChecked()]

   def _show_template(self) -> None:
      """!Shows the chosen template's description and files; parts it does not give are off.
      @return None
      """
      t = self.template()
      if t is None:
         self.description.setText("No templates found.")
         self.create_button.setEnabled(False)
         return
      lines = [f"<b>{t.name}</b> &middot; {templates.ORIGIN_TEXT.get(t.origin, t.origin)}, version {t.version}",
               t.description]
      for part, files in t.parts.items():
         lines.append(f"<i>{part}</i>: {', '.join(files)}")
      self.description.setText("<br><br>".join(line for line in lines if line))
      for part, box in self.part_boxes.items():
         box.setEnabled(self.mode == BATTLE and part in t.parts)
      self.create_button.setEnabled(True)

   def browse(self) -> None:
      """!Picks the target folder.
      @return None
      """
      title = "Folder for the new game" if self.mode == GAME else "Folder for the new battle data"
      folder = QtWidgets.QFileDialog.getExistingDirectory(self, title, self.folder.text())
      if folder:
         self.folder.setText(folder)

   # -- creating ------------------------------------------------------------------------------------------------------

   def create(self) -> Path | None:
      """!Makes the game or copies the battle data (nothing is overwritten); a refusal shows in the dialog.
      @return the project manifest (GAME) or the battle manifest (BATTLE), or None when refused
      """
      t = self.template()
      folder = self.folder.text().strip()
      try:
         if t is None:
            raise DocumentError("no template is chosen")
         if not folder:
            raise DocumentError("name the folder")
         if self.mode == GAME:
            self.created = templates.new_game(Path(folder), t, self.name.text().strip() or None)
         else:
            parts = self.parts()
            if not parts:
               raise DocumentError("tick at least one part")
            written = templates.apply(t, Path(folder), parts)
            # the copied battle manifest, or (some parts only) the one the folder has already
            battle = templates.game_manifests(written).get("battle")
            present = Path(folder) / BATTLE_FILE
            if battle is None and present.is_file():
               battle = present
            if battle is None:
               raise DocumentError(f"copied {len(written)} file(s), but the folder has no {BATTLE_FILE} yet: copy "
                                   "the content part too to open it")
            self.created = battle
      except (DocumentError, OSError) as e:
         self.message.setText(str(e))
         self.message.setVisible(True)
         return None
      return self.created

   def _create_and_close(self) -> None:
      """!Create: closes the dialog when it worked.
      @return None
      """
      if self.create() is not None:
         self.accept()
