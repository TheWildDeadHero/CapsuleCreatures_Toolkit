"""!The Data panel ("Other data"): traits and the other top-level settings
of the battle manifest that have no page of their own yet, edited as JSON.
Categories, the condition records (statuses, volatiles, weathers, side /
field conditions), move flags, tags, passives and items have their own pages
(Structure > Categories, Conditions, Flags & Tags; Content > Passives /
Items, S5b), and so do formats, the turn and the progression rules
(Structure > Formats, Turn, Progression, S5c), and so do the messages
(Content > Messages, S11): they are not shown here.
Each section lives in one file of the battle data (E5s): traits in
battle.json, the rules, stats, growth and record layout in the structure
manifest; the page names the file of the section it shows, and Undo / Save
act on that file.

It edits the host's BattleProject (core.battle) through host.run_edit(); the
engine's battle compiler checks the values and its message shows under the
form.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtWidgets

from ....core import battle
from ...widgets import button, set_enabled
from ..battle_common import FORM_STRETCH, LIST_STRETCH, BattlePanel
from .json_edit import JsonEdit

if TYPE_CHECKING:
   from ....core.document import Document
   from ...panel import PanelHost
   from ..battle_common import JsonValue

## Kinds the JSON panel shows as lists (one entry at a time).
JSON_LISTS = ["traits"]
## Top-level objects the JSON panel shows whole.
JSON_OBJECTS = ["rules", "stats", "growth", "monster_layout"]


class DataPanel(BattlePanel):
   """!Traits and the other top-level settings without a page of
   their own, edited as JSON.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## See EditorPanel.panel_id.
   panel_id = "data"
   ## See EditorPanel.title.
   title = "Other data"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the kind / entry choosers and the JSON editor.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## (part, entry row) the JSON editor last showed (another one discards unapplied typing).
      self._shown_for = None
      ## What is shown.
      self.what = QtWidgets.QComboBox()
      self.what.addItems(JSON_LISTS + JSON_OBJECTS)
      self.what.currentIndexChanged.connect(lambda *a: self._section_changed())
      ## Entries of a list kind.
      self.entry_list = QtWidgets.QListWidget()
      self.entry_list.currentRowChanged.connect(lambda *a: self._fill_json())
      ## The JSON editor.
      self.json = JsonEdit(lambda v: self.apply(v))
      ## Which file the shown section is in.
      self.file_label = QtWidgets.QLabel()
      left = QtWidgets.QVBoxLayout()
      left.addWidget(self.what)
      left.addWidget(self.file_label)
      left.addWidget(self.entry_list, 1)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("New", lambda: self.new_entry()))
      row.addWidget(button("Delete", lambda: self.delete_entry()))
      left.addLayout(row)
      right = QtWidgets.QVBoxLayout()
      right.addWidget(self.json, 1)
      right.addWidget(self.errors)
      lay = QtWidgets.QHBoxLayout(self)
      for part, stretch in ((left, LIST_STRETCH), (right, FORM_STRETCH)):
         box = QtWidgets.QWidget()
         box.setLayout(part)
         lay.addWidget(box, stretch)

   def kind(self) -> str:
      """!The chosen kind or object.
      @return name
      """
      return self.what.currentText()

   def _section_changed(self) -> None:
      """!Another section is shown: refill, and tell the host the page's file may be another one now.
      @return None
      """
      self.refresh()
      self.host.selection_changed()

   def manifest_doc(self) -> Document | None:
      """!The file the shown section is in (the battle or the structure manifest: core.battle.part_of()).
      @return Document, or None
      """
      p = self.project()
      return battle.part_of(p.battle, self.kind()) if p is not None else None

   def refresh(self) -> None:
      """!Re-reads the list and the JSON.
      @return None
      """
      p = self.project()
      k = self.kind()
      doc = self.manifest_doc()
      self.file_label.setText(f"In {doc.path.name}" if doc is not None and doc.path is not None else "")
      self._filling = True
      try:
         row = self.entry_list.currentRow()
         self.entry_list.clear()
         if p is not None and k in JSON_LISTS:
            self.entry_list.addItems(p.names(k))
            n = self.entry_list.count()
            self.entry_list.setCurrentRow(min(max(row, 0), n - 1) if n else -1)
         set_enabled(self.entry_list, k in JSON_LISTS)   # read-only lists still scroll
      finally:
         self._filling = False
      self._fill_json()
      self.show_errors()

   def _fill_json(self) -> None:
      """!Shows the chosen entry or object.
      @return None
      """
      p = self.project()
      k = self.kind()
      if p is None:
         self.json.set_value(None)
         return
      i = self.entry_list.currentRow() if k in JSON_LISTS else -1
      data = battle.data_of(p.battle, k)
      if k in JSON_LISTS:
         lst = data.get(k, [])
         value = lst[i] if 0 <= i < len(lst) else None
      else:
         value = data.get(k)
      shown_for = (k, i)
      if shown_for != self._shown_for:
         self._shown_for = shown_for
         self.json.discard(value)
      else:
         self.json.set_value(value)

   def apply(self, value: JsonValue) -> None:
      """!Writes the edited JSON back.
      @param value  parsed JSON
      @return None
      """
      p = self.project()
      if p is None:
         return
      k = self.kind()
      doc = battle.part_of(p.battle, k)
      if k in JSON_LISTS:
         i = self.entry_list.currentRow()
         if not (0 <= i < len(doc.data.get(k, []))):
            return
         if not isinstance(value, dict) or not isinstance(value.get("name"), str) or not value["name"].strip():
            self.json.status.setText("An entry is an object with a \"name\".")
            return
         value["name"] = value["name"].strip()
         if k == "traits":
            battle.with_trait_pct(value)   # E7: a trait with up / down states its percentages
         old = doc.data[k][i].get("name")

         def fn() -> None:
            """!Renames the entry when its name changed (references follow), then replaces it."""
            if value["name"] != old:
               battle.rename_entry(doc, k, old, value["name"])
            doc.data[k][i] = value
         self.host.run_edit(f"Edit {self.kind_word(k)}", fn, doc)
      else:
         self.host.run_edit(f"Edit {k}", lambda: doc.data.__setitem__(k, value), doc)   # a whole object

   def new_entry(self) -> None:
      """!Adds an entry to a list kind.
      @return None
      """
      k = self.kind()
      if k not in JSON_LISTS:
         return
      word = self.kind_word(k)
      name, ok = QtWidgets.QInputDialog.getText(self, "New " + word, "Name:")
      if ok and name.strip():
         self.edit("New " + word, lambda: battle.add_entry(self.battle_doc(), k, name))

   def delete_entry(self) -> None:
      """!Deletes the chosen entry (refused while referenced).
      @return None
      """
      k = self.kind()
      i = self.entry_list.currentRow()
      p = self.project()
      if k not in JSON_LISTS or p is None or not 0 <= i < len(p.names(k)):
         return
      name = p.names(k)[i]
      self.edit("Delete " + self.kind_word(k), lambda: battle.remove_entry(p.battle, k, name))
