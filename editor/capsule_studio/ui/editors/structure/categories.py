"""!The Categories panel (D-23 §3.2 "Categories"): the battle manifest's move
categories, at most the engine's MAX_CATEGORIES.

The table edits a category's name (a rename follows the moves,
rules.self_hit.category and the effect logic), whether it deals formula
damage and the two stats that damage uses (any stat but the pool stat). It
shows how many moves take each category and which one the self-hit uses.
A mode combo says where a damaging move's category comes from: the move
(it names its category) or its type (the structure's category_by_type,
E11); in the type mode a second table gives each type its damaging category
(choices: the categories the engine's compiler calls damaging). In the move
mode a box turns on the hit types' categories (engine C5, the structure's
hit_category_by_type: a damaging move whose type the ruleset's move_type
point changed hits with that type's category) and a third table gives each
type its one. Every change is one undo step (core.structure.categories); the
compile result shows at the bottom.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

from ....core.document import DocumentError
from ....core.structure import categories as cat_model
from ...panes import split_box
from ...widgets import button, set_enabled
from ..battle_common import STRUCTURE, BattlePanel

if TYPE_CHECKING:
   from ....core.document import Document
   from ...panel import PanelHost

## Table columns: (category_rows() key, header).
CATEGORY_COLUMNS = [("index", "#"), ("name", "Name"), ("damaging", "Damaging"), ("offense", "Offense"),
                    ("defense", "Defense"), ("moves", "Moves"), ("self_hit", "Self-hit")]
## Table column of each key.
CATEGORY_COLUMN = {key: c for c, (key, _h) in enumerate(CATEGORY_COLUMNS)}
## Text colour of a budget over its limit.
OVER_COLOR = "#c03030"
## Text colour of a budget within its limit.
WITHIN_COLOR = "#2a7a2a"
## Self-hit column text of the category rules.self_hit uses.
SELF_HIT_TEXT = "yes"
## The mode combo's entries: (core mode, text).
MODE_TEXTS = [(cat_model.BY_MOVE, "the move (each move names its category)"),
              (cat_model.BY_TYPE, "its type (category_by_type)")]
## By-type table columns: (type_rows() key, header).
TYPE_COLUMNS = [("type", "Type"), ("category", "Category"), ("moves", "Damaging moves")]
## By-type table column of each key.
TYPE_COLUMN = {key: c for c, (key, _h) in enumerate(TYPE_COLUMNS)}
## Hit types' table columns: (hit_rows() key, header).
HIT_COLUMNS = [("type", "Hit type"), ("category", "Category")]
## Hit types' table column of each key.
HIT_COLUMN = {key: c for c, (key, _h) in enumerate(HIT_COLUMNS)}


class CategoriesPanel(BattlePanel):
   """!The categories table.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   @var type_boxes
   The by-type table's category combos, by type name.
   @var hit_boxes
   The hit types' table's category combos, by type name (C5).
   """

   ## See EditorPanel.panel_id.
   ## The file the page edits: the structure manifest.
   manifest = STRUCTURE
   panel_id = "categories"
   ## See EditorPanel.title.
   title = "Categories"
   ## The kind whose game word is the title (see BattlePanel.title_kind).
   title_kind = "categories"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the table and the buttons.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## Name of the selected category, or None.
      self.selected = None
      ## Categories used against the engine's cap.
      self.budget = QtWidgets.QLabel()
      ## The categories.
      self.table = QtWidgets.QTableWidget(0, len(CATEGORY_COLUMNS))
      self.table.setHorizontalHeaderLabels([h for _k, h in CATEGORY_COLUMNS])
      self.table.verticalHeader().setVisible(False)
      self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
      self.table.itemChanged.connect(lambda item: self._cell_changed(item))
      self.table.itemSelectionChanged.connect(lambda: self._selection_changed())
      ## Cell widgets by row: {"damaging": QCheckBox, "offense": QComboBox, "defense": QComboBox}.
      self.row_widgets = []
      ## Where a damaging move's category comes from (MODE_TEXTS; BY_TYPE only when the engine has it).
      self.mode_box = QtWidgets.QComboBox()
      self.mode_box.setToolTip("By type: each type takes its moves' most common damaging category (a damaging "
                               "move of another one takes its type's); by move: every move keeps its category")
      self.mode_box.activated.connect(lambda _i: self._mode_picked())
      ## The by-type rule: one row per type (shown in the type mode).
      self.type_table = QtWidgets.QTableWidget(0, len(TYPE_COLUMNS))
      self.type_table.setHorizontalHeaderLabels([h for _k, h in TYPE_COLUMNS])
      self.type_table.verticalHeader().setVisible(False)
      self.type_boxes = {}
      ## Title of the by-type table.
      self.type_title = QtWidgets.QLabel("Category by type: a damaging move takes its type's category (a status "
                                         "move still names its own)")
      self.type_title.setWordWrap(True)
      ## The move mode's hit types' categories on / off (C5: hit_category_by_type).
      self.hit_box = QtWidgets.QCheckBox("A hit whose type is not its move's own (the move_type point changed it) "
                                         "takes that type's category")
      self.hit_box.setToolTip("A move whose type changes when it is used: the category follows the type it hits with "
                              "(the structure's hit_category_by_type; each type starts with its moves' most "
                              "common damaging category)")
      self.hit_box.clicked.connect(lambda on: self._hit_clicked(bool(on)))
      ## The hit types' categories: one row per type (shown while they are on).
      self.hit_table = QtWidgets.QTableWidget(0, len(HIT_COLUMNS))
      self.hit_table.setHorizontalHeaderLabels([h for _k, h in HIT_COLUMNS])
      self.hit_table.verticalHeader().setVisible(False)
      self.hit_boxes = {}
      lay = QtWidgets.QVBoxLayout(self)
      note = QtWidgets.QLabel("A category's damage attacks with its offense stat against the target's defense stat "
                              "(a category without them deals no formula damage). A move names its category "
                              "(default: the first), or its type decides a damaging move's category.")
      note.setWordWrap(True)
      lay.addWidget(note)
      lay.addWidget(self.budget)
      lay.addWidget(self.table, 1)
      mode_row = QtWidgets.QHBoxLayout()
      mode_row.addWidget(QtWidgets.QLabel("A damaging move's category comes from"))
      mode_row.addWidget(self.mode_box)
      mode_row.addStretch(1)
      lay.addLayout(mode_row)
      lay.addWidget(self.type_title)
      lay.addWidget(self.type_table, 1)
      lay.addWidget(self.hit_box)
      lay.addWidget(self.hit_table, 1)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add...", lambda: self.add_category(), "Add a non-damaging category"))
      row.addWidget(button("Remove", lambda: self.remove_category(), "Remove the selected one (nothing may name it)"))
      row.addWidget(button("Rename...", lambda: self.rename_category(), "Rename it; moves and logic follow"))
      row.addWidget(button("Up", lambda: self.move_category(-1), "Lower index (the first is the moves' default)"))
      row.addWidget(button("Down", lambda: self.move_category(1), "Higher index"))
      row.addStretch(1)
      lay.addLayout(row)
      lay.addWidget(self.errors)
      split_box(lay)   # [RZ] the three tables, stacked: the user drags the boundaries

   def rows(self) -> list[cat_model.CategoryRow]:
      """!The categories as the table shows them.
      @return category_rows() ([] with nothing open)
      """
      doc = self.battle_doc()
      return cat_model.category_rows(doc) if doc is not None else []

   def refresh(self) -> None:
      """!Re-reads the categories.
      @return None
      """
      doc = self.battle_doc()
      rows = self.rows()
      names = [r["name"] for r in rows]
      if self.selected not in names:
         self.selected = names[0] if names else None
      stats = cat_model.damage_stats(doc) if doc is not None else []
      most = cat_model.max_categories()
      self._filling = True
      try:
         self.budget.setText(f"{len(rows)}/{most} categories" if doc is not None else "")
         self.budget.setStyleSheet(f"color: {OVER_COLOR if len(rows) > most else WITHIN_COLOR}; font-weight: bold;")
         self.table.setRowCount(len(rows))
         self.row_widgets = []
         editable = QtCore.Qt.ItemFlag.ItemIsEditable
         for r, row in enumerate(rows):
            for key in ("index", "name", "moves", "self_hit", "damaging", "offense", "defense"):
               text = {"index": str(row["index"]), "name": str(row["name"]), "moves": str(row["moves"]),
                       "self_hit": SELF_HIT_TEXT if row["self_hit"] else ""}.get(key, "")
               item = QtWidgets.QTableWidgetItem(text)
               if key != "name":
                  item.setFlags(item.flags() & ~editable)
               self.table.setItem(r, CATEGORY_COLUMN[key], item)
            name = row["name"]
            damaging = QtWidgets.QCheckBox()
            damaging.setChecked(row["damaging"])
            damaging.clicked.connect(lambda on, n=name: self._damaging_clicked(n, bool(on)))
            self.table.setCellWidget(r, CATEGORY_COLUMN["damaging"], damaging)
            widgets = {"damaging": damaging}
            for key in ("offense", "defense"):
               box = QtWidgets.QComboBox()
               box.addItems(stats + ([str(row[key])] if row[key] is not None and row[key] not in stats else []))
               if row[key] is None:
                  box.setCurrentIndex(-1)   # non-damaging: no stat shown
               else:
                  box.setCurrentText(str(row[key]))
               box.setEnabled(row["damaging"])
               box.activated.connect(lambda _i, n=name: self._stats_picked(n))
               self.table.setCellWidget(r, CATEGORY_COLUMN[key], box)
               widgets[key] = box
            self.row_widgets.append(widgets)
         self.table.resizeColumnsToContents()
         if self.selected in names:
            self.table.selectRow(names.index(self.selected))
         self._fill_mode(doc)
      finally:
         self._filling = False
      set_enabled(self.table, doc is not None)   # read-only, still scrolling
      self.show_errors()

   def _fill_mode(self, doc: Document | None) -> None:
      """!Fills the mode combo and the by-type table.
      @param doc  the battle Document, or None
      @return None
      """
      available = cat_model.modes()
      self.mode_box.clear()
      for mode, text in MODE_TEXTS:
         if mode in available:
            self.mode_box.addItem(text, mode)
      current = cat_model.mode(doc) if doc is not None else cat_model.BY_MOVE
      self.mode_box.setCurrentIndex(max(0, self.mode_box.findData(current)))
      self.mode_box.setEnabled(doc is not None and len(available) > 1)
      rows = cat_model.type_rows(doc) if doc is not None else []
      try:
         choices = cat_model.damaging_categories(doc) if doc is not None else []
      except DocumentError:
         choices = []
      self.type_table.setRowCount(len(rows))
      self.type_boxes = {}
      fixed = ~QtCore.Qt.ItemFlag.ItemIsEditable
      for r, row in enumerate(rows):
         for key in ("type", "moves"):
            item = QtWidgets.QTableWidgetItem(str(row[key]))
            item.setFlags(item.flags() & fixed)
            self.type_table.setItem(r, TYPE_COLUMN[key], item)
         box = QtWidgets.QComboBox()
         box.addItems(choices + ([str(row["category"])] if row["category"] not in choices + [None] else []))
         box.setCurrentText(str(row["category"]) if row["category"] is not None else "")
         box.activated.connect(lambda _i, t=row["type"]: self._type_picked(t))
         self.type_table.setCellWidget(r, TYPE_COLUMN["category"], box)
         self.type_boxes[row["type"]] = box
      self.type_table.resizeColumnsToContents()
      by_type = current == cat_model.BY_TYPE
      self.type_title.setVisible(by_type)
      self.type_table.setVisible(by_type)
      self._fill_hits(doc, choices, by_type)

   def _fill_hits(self, doc: Document | None, choices: list[str], by_type: bool) -> None:
      """!Fills the hit types' box and table (C5; the move mode only: by type, category_by_type gives them).
      @param doc      the battle Document, or None
      @param choices  the damaging categories
      @param by_type  the type mode is on
      @return None
      """
      available = cat_model.hit_available() and not by_type
      rows = cat_model.hit_rows(doc) if doc is not None and available else []
      self.hit_box.setVisible(available)
      self.hit_box.setEnabled(doc is not None)
      self.hit_box.setChecked(bool(rows))
      self.hit_table.setRowCount(len(rows))
      self.hit_boxes = {}
      fixed = ~QtCore.Qt.ItemFlag.ItemIsEditable
      for r, row in enumerate(rows):
         item = QtWidgets.QTableWidgetItem(str(row["type"]))
         item.setFlags(item.flags() & fixed)
         self.hit_table.setItem(r, HIT_COLUMN["type"], item)
         box = QtWidgets.QComboBox()
         box.addItems(choices + ([str(row["category"])] if row["category"] not in choices + [None] else []))
         box.setCurrentText(str(row["category"]) if row["category"] is not None else "")
         box.activated.connect(lambda _i, ty=row["type"]: self._hit_picked(ty))
         self.hit_table.setCellWidget(r, HIT_COLUMN["category"], box)
         self.hit_boxes[row["type"]] = box
      self.hit_table.resizeColumnsToContents()
      self.hit_table.setVisible(bool(rows))

   def _hit_clicked(self, on: bool) -> None:
      """!The hit types' box was clicked.
      @param on  checked
      @return None
      """
      if not self._filling:
         self.set_hit(on)

   def _hit_picked(self, type_name: str) -> None:
      """!A hit type's category combo was picked.
      @param type_name  its type
      @return None
      """
      if not self._filling:
         self.set_hit_category(type_name, self.hit_boxes[type_name].currentText())

   def set_hit(self, on: bool) -> bool:
      """!Turns the hit types' categories on or off (one undo step; C5).
      @param on  True: hit_category_by_type; False: a moved type keeps the move's category
      @return True when the edit went through
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      return self._edit("Hit categories", lambda: cat_model.set_hit(doc, on))

   def set_hit_category(self, type_name: str, category: str) -> bool:
      """!Sets the category a hit of a type takes (one undo step).
      @param type_name  the type
      @param category   a damaging category
      @return True when the edit went through
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      return self._edit("Hit type category", lambda: cat_model.set_hit_category(doc, type_name, category))

   def _mode_picked(self) -> None:
      """!The mode combo was picked.
      @return None
      """
      if not self._filling:
         self.set_mode(str(self.mode_box.currentData()))

   def _type_picked(self, type_name: str) -> None:
      """!A by-type category combo was picked.
      @param type_name  its type
      @return None
      """
      if not self._filling:
         self.set_type_category(type_name, self.type_boxes[type_name].currentText())

   def set_mode(self, mode: str) -> bool:
      """!Switches where damaging moves take their category from (one undo step; moves keep their categories).
      @param mode  cat_model.BY_MOVE or BY_TYPE
      @return True when the edit went through
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      return self._edit("Category mode", lambda: cat_model.set_mode(doc, mode))

   def set_type_category(self, type_name: str, category: str) -> bool:
      """!Sets a type's damaging category (one undo step).
      @param type_name  the type
      @param category   a damaging category
      @return True when the edit went through
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      return self._edit("Type category", lambda: cat_model.set_type_category(doc, type_name, category))

   # -- editing ------------------------------------------------------------------------

   def _edit(self, label: str, fn: object) -> bool:
      """!One edit; a refused one refreshes the table back.
      @param label  undo label
      @param fn     callable
      @return True when it went through
      """
      ok = self.edit(label, fn)
      if not ok:
         self.host.changed()
      return ok

   def _selection_changed(self) -> None:
      """!Another row was picked.
      @return None
      """
      if self._filling:
         return
      rows = self.table.selectionModel().selectedRows()
      all_rows = self.rows()
      if rows and rows[0].row() < len(all_rows):
         self.selected = all_rows[rows[0].row()]["name"]

   def _cell_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A name was typed: renames the category.
      @param item  the cell
      @return None
      """
      rows = self.rows()
      if self._filling or item.column() != CATEGORY_COLUMN["name"] or not 0 <= item.row() < len(rows):
         return
      old, new = rows[item.row()]["name"], item.text().strip()
      if new != old:
         self.rename_category(new, old)

   def _damaging_clicked(self, name: str, on: bool) -> None:
      """!The damaging box was clicked: on takes the first two damage stats, off drops them.
      @param name  the category
      @param on    damaging
      @return None
      """
      doc = self.battle_doc()
      stats = cat_model.damage_stats(doc) if doc is not None else []
      if on and stats:
         self.set_damage(name, stats[0], stats[1] if len(stats) > 1 else stats[0])
      else:
         self.set_damage(name, None, None)

   def _stats_picked(self, name: str) -> None:
      """!An offense or defense combo was picked.
      @param name  the category
      @return None
      """
      i = [r["name"] for r in self.rows()].index(name)
      w = self.row_widgets[i]
      self.set_damage(name, w["offense"].currentText(), w["defense"].currentText())

   def set_damage(self, name: str, offense: str | None, defense: str | None) -> bool:
      """!Sets the stats a category's damage uses (both None: non-damaging; one undo step).
      @param name     category name
      @param offense  stat or None
      @param defense  stat or None
      @return True when the edit went through
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      return self._edit("Category damage", lambda: cat_model.set_damage(doc, name, offense, defense))

   def add_category(self, name: str | None = None, offense: str | None = None, defense: str | None = None) -> bool:
      """!Adds a category after the selected one.
      @param name     its name, or None to ask
      @param offense  damage stat, or None (non-damaging)
      @param defense  damage stat, or None
      @return True when added
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, "Add category", "Name:")
         if not ok:
            return False
      names = [r["name"] for r in self.rows()]
      at = names.index(self.selected) + 1 if self.selected in names else None
      if self._edit("Add category", lambda: cat_model.add_category(doc, name, offense, defense, at)):
         self.selected = name.strip()
         return True
      return False

   def remove_category(self) -> bool:
      """!Removes the selected category (refused while named).
      @return True when removed
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      if self._edit("Remove category", lambda: cat_model.remove_category(doc, name)):
         self.selected = None
         return True
      return False

   def rename_category(self, new: str | None = None, old: str | None = None) -> bool:
      """!Renames a category; moves, rules.self_hit and the effect logic follow.
      @param new  the new name, or None to ask
      @param old  the category, or None for the selected one
      @return True when renamed
      """
      doc = self.battle_doc()
      old = old or self.selected
      if doc is None or old is None:
         return False
      if new is None:
         new, ok = QtWidgets.QInputDialog.getText(self, "Rename category", "New name:", text=old)
         if not ok:
            return False
      if not new.strip() or new.strip() == old:
         self.host.changed()
         return False
      if self._edit("Rename category", lambda: cat_model.rename_category(doc, old, new)):
         self.selected = new.strip()
         return True
      return False

   def move_category(self, delta: int) -> bool:
      """!Moves the selected category up or down.
      @param delta  -1 up, +1 down
      @return True when it moved
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      moved = []
      ok = self._edit("Move category", lambda: moved.append(cat_model.move_category(doc, name, delta)))
      return ok and moved == [True]
