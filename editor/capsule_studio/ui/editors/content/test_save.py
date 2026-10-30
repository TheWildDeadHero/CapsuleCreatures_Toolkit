"""!The Test save (Bag) page (D-26 section 2, engine G2): a test save's bag,
pocket by pocket (core.inventory: the game folder's testsaves/NAME.json,
capsule.testsave/1).

Pick a test save (or make a new one), pick a pocket, then Put / Take items:
only the pocket's own items are offered (an item's pocket is its Content >
Items field), up to the pocket's slots and its most of one item (Structure >
Pockets). The problems line names what the battle data refuses (an item that
moved pockets, a pocket that shrank). Export... writes the engine save image
of the bag (the engine's tools/save_layout.py: an empty party, zero script
banks), which a desktop build of the game loads as its save file. G3: the
Boxes box puts creatures (a species and a level) into the storage boxes
(Structure > Storage), the current box first, and sets the current box; the
export writes them as engine records. F3: the Step counters box shows each
step effect (Structure > Step effects) with the steps the save has counted
towards its next run; Set changes the selected one (0 to every - 1), the
export writes them into the script banks (the effects' implicit variables).
B2: a boxed creature may be an egg (Egg sets the selected one's hatch
counter, Not egg clears it), and the Nursery box shows the nursery's slots
(Structure > Nursery) with the record each holds (its level when left and the
experience gained there; Leave / Take back) and the waiting result (an egg
with its hatch counter, or a creature); the export writes them into the
Nursery section.
S5 (engine N3): the Game box shows the save's game block when the engine's
save layout has a Game section (core.game_block): the game's version of its
block, the block's size (both the game's C++: game_block_bytes()), its bytes
as hex (Apply writes them; the rest of the block is zeros), From a save
file... (the Game section of a save the game wrote) and Remove; the export
writes it into the image's Game section.
Every change is saved to the test save at once (it is its own file, outside
the battle data's undo).
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6 import QtWidgets

from ....core import battle, game_block, inventory, save_shapes
from ....core.document import Document, DocumentError
from ....core.structure import nursery as nursery_model
from ....core.structure import pockets as pocket_model
from ....core.structure import step_effects as step_model
from ....core.structure import storage as storage_model
from ...widgets import button, report_failure, set_enabled
from ..battle_common import NONE_TEXT, BattlePanel, set_check, set_combo, set_spin_max

if TYPE_CHECKING:
   from ...panel import PanelHost

## Slot table columns.
SLOT_COLUMNS = ["Item", "Count"]
## Column of the item.
ITEM_COLUMN = 0
## Column of the count.
COUNT_COLUMN = 1
## File dialog filter of an exported image.
IMAGE_FILTER = "Save image (*.sav);;All files (*)"
## Text colour of the problems line.
PROBLEM_COLOR = "#c03030"
## Text colour of a save that checks.
OK_COLOR = "#2a7a2a"
## Boxed creature table columns (G3).
BOXED_COLUMNS = ["Slot", "Box", "Species", "Level", "Egg (steps left)"]
## Column of the slot.
SLOT_COLUMN = 0
## Column of the box.
BOX_COLUMN = 1
## Column of the species.
SPECIES_COLUMN = 2
## Column of the level.
LEVEL_COLUMN = 3
## Column of an egg's hatch counter (B2).
EGG_COLUMN = 4
## Nursery slot table columns (B2).
HELD_COLUMNS = ["Slot", "Species", "Level when left", "Experience gained"]
## Columns of the nursery table.
HELD_SLOT_COLUMN, HELD_SPECIES_COLUMN, HELD_LEVEL_COLUMN, HELD_GAINED_COLUMN = range(len(HELD_COLUMNS))
## What an empty nursery slot shows.
EMPTY_SLOT = "(empty)"
## The most experience the gained spin offers (Qt's int; the save holds a u32).
MAX_GAINED_SPIN = 0x7FFFFFFF
## Step counter table columns (F3).
STEP_COLUMNS = ["Step effect", "Counted", "Every", "Next run in"]
## Column of the effect.
STEP_NAME_COLUMN = 0
## Column of the steps counted.
STEP_COUNT_COLUMN = 1
## Column of every.
STEP_EVERY_COLUMN = 2
## Column of the steps to the next run.
STEP_LEFT_COLUMN = 3
## S5: the most bytes the game block's size spin offers (Qt's int; the section holds a u32).
MAX_BLOCK_SPIN = 0x7FFFFFFF
## S5: rows of hex the Game box shows before it scrolls.
GAME_HEX_ROWS = 6
## S5: file dialog filter of a save file to read the game block from.
SAVE_FILE_FILTER = "Save file (*.sav *.bin);;All files (*)"


class TestSavePanel(BattlePanel):
   """!A test save's bag.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## See EditorPanel.panel_id.
   panel_id = "test_save"
   ## See EditorPanel.title.
   title = "Test save (Bag)"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the save picker, the pocket picker, the slot table and the Put / Take row.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The open test save, or None.
      self.save = None
      ## The shown pocket's name, or None.
      self.pocket = None
      ## The game's test saves.
      self.saves = QtWidgets.QComboBox()
      self.saves.activated.connect(lambda _i: self.open_save(self.saves.currentText()))
      ## The pockets.
      self.pockets = QtWidgets.QComboBox()
      self.pockets.activated.connect(lambda _i: self.show_pocket(self.pockets.currentText()))
      ## The pocket's slots.
      self.table = QtWidgets.QTableWidget(0, len(SLOT_COLUMNS))
      self.table.setHorizontalHeaderLabels(SLOT_COLUMNS)
      self.table.verticalHeader().setVisible(False)
      self.table.horizontalHeader().setStretchLastSection(True)
      self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      ## The pocket's items to put.
      self.item_choice = QtWidgets.QComboBox()
      ## How many to put or take.
      self.count = QtWidgets.QSpinBox()
      self.count.setRange(1, pocket_model.max_quantity())   # the engine's MAX_QUANTITY; a pocket sets its own
      ## The pocket's slots and most of one item.
      self.pocket_info = QtWidgets.QLabel()
      ## What the battle data refuses.
      self.problems = QtWidgets.QLabel()
      self.problems.setWordWrap(True)
      top = QtWidgets.QHBoxLayout()
      top.addWidget(QtWidgets.QLabel("Test save"))
      top.addWidget(self.saves, 1)
      top.addWidget(button("New...", lambda: self.new_save()))
      top.addWidget(button("Export...", lambda: self.export_save(),
                           "Write the engine save image of this bag and its boxes"))
      pocket_row = QtWidgets.QHBoxLayout()
      pocket_row.addWidget(QtWidgets.QLabel("Pocket"))
      pocket_row.addWidget(self.pockets, 1)
      pocket_row.addWidget(self.pocket_info)
      put_row = QtWidgets.QHBoxLayout()
      put_row.addWidget(self.item_choice, 1)
      put_row.addWidget(self.count)
      put_row.addWidget(button("Put", lambda: self.put(self.item_choice.currentText(), self.count.value())))
      put_row.addWidget(button("Take", lambda: self.take_selected(self.count.value())))
      lay = QtWidgets.QVBoxLayout(self)
      lay.addLayout(top)
      lay.addLayout(pocket_row)
      lay.addWidget(self.table, 1)
      lay.addLayout(put_row)
      lay.addWidget(self._build_boxes())
      lower = QtWidgets.QHBoxLayout()
      lower.addWidget(self._build_steps(), 1)
      lower.addWidget(self._build_nursery(), 1)
      lay.addLayout(lower)
      lay.addWidget(self._build_game())
      lay.addWidget(self._build_shapes())
      lay.addWidget(self.problems)
      lay.addWidget(self.errors)

   def _build_boxes(self) -> QtWidgets.QGroupBox:
      """!Builds the Boxes box (G3): the current box, the boxed creatures and the Box / Unbox row.
      @return the box
      """
      ## The current box.
      self.current = QtWidgets.QComboBox()
      self.current.activated.connect(lambda i: self.set_current_box(i))
      ## The boxed creatures.
      self.boxed = QtWidgets.QTableWidget(0, len(BOXED_COLUMNS))
      self.boxed.setHorizontalHeaderLabels(BOXED_COLUMNS)
      self.boxed.verticalHeader().setVisible(False)
      self.boxed.horizontalHeader().setStretchLastSection(True)
      self.boxed.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.boxed.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      ## The species to box.
      self.species_choice = QtWidgets.QComboBox()
      ## Its level.
      self.level = QtWidgets.QSpinBox()
      self.level.setRange(1, storage_model.NEW_LEVEL)   # the record layout's top: _fill_boxes()
      self.level.setValue(storage_model.NEW_LEVEL)
      box = QtWidgets.QGroupBox("Boxes")
      row = QtWidgets.QHBoxLayout()
      row.addWidget(QtWidgets.QLabel("Current box"))
      row.addWidget(self.current, 1)
      put = QtWidgets.QHBoxLayout()
      put.addWidget(self.species_choice, 1)
      put.addWidget(QtWidgets.QLabel("Level"))
      put.addWidget(self.level)
      put.addWidget(button("Box", lambda: self.box_creature(self.species_choice.currentText(), self.level.value()),
                           "Put a creature into the current box (else the first free slot)"))
      put.addWidget(button("Unbox", lambda: self.unbox_selected(), "Take the selected creature out"))
      ## B2: the hatch counter Egg gives the selected creature.
      self.box_hatch = QtWidgets.QSpinBox()
      self.box_hatch.setRange(0, 0)   # the counter role's top: _fill_boxes()
      put.addWidget(QtWidgets.QLabel("Steps left"))
      put.addWidget(self.box_hatch)
      ## Makes the selected creature an egg.
      self.egg_button = button("Egg", lambda: self.set_boxed_egg(self.box_hatch.value()),
                               "Make the selected creature an egg with these steps left")
      put.addWidget(self.egg_button)
      ## Makes it a creature again.
      self.not_egg_button = button("Not egg", lambda: self.set_boxed_egg(None), "The selected egg is a creature again")
      put.addWidget(self.not_egg_button)
      lay = QtWidgets.QVBoxLayout(box)
      lay.addLayout(row)
      lay.addWidget(self.boxed)
      lay.addLayout(put)
      return box

   def _build_nursery(self) -> QtWidgets.QGroupBox:
      """!Builds the Nursery box (B2): the slots with their records, the Leave / Take back row and the waiting result.
      @return the box
      """
      ## The nursery's slots.
      self.held = QtWidgets.QTableWidget(0, len(HELD_COLUMNS))
      self.held.setHorizontalHeaderLabels(HELD_COLUMNS)
      self.held.verticalHeader().setVisible(False)
      self.held.horizontalHeader().setStretchLastSection(True)
      self.held.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.held.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      ## The species to leave.
      self.held_species = QtWidgets.QComboBox()
      ## Its level when left.
      self.held_level = QtWidgets.QSpinBox()
      self.held_level.setRange(1, nursery_model.MAX_SLOT_LEVEL)
      self.held_level.setValue(nursery_model.NEW_LEVEL)
      ## The experience it gained there.
      self.held_gained = QtWidgets.QSpinBox()
      self.held_gained.setRange(0, MAX_GAINED_SPIN)
      ## The waiting result's species ("(none)": nothing waits).
      self.result_species = QtWidgets.QComboBox()
      self.result_species.activated.connect(lambda _i: self.set_result_from_form())
      ## Whether it is an egg.
      self.result_egg = QtWidgets.QCheckBox("Egg, steps left")
      self.result_egg.clicked.connect(lambda _on: self.set_result_from_form())
      ## Its hatch counter.
      self.result_hatch = QtWidgets.QSpinBox()
      self.result_hatch.setRange(0, 0)
      self.result_hatch.editingFinished.connect(lambda: self.set_result_from_form())
      box = QtWidgets.QGroupBox("Nursery (Structure > Nursery)")
      put = QtWidgets.QHBoxLayout()
      put.addWidget(self.held_species, 1)
      put.addWidget(QtWidgets.QLabel("Level"))
      put.addWidget(self.held_level)
      put.addWidget(QtWidgets.QLabel("Gained"))
      put.addWidget(self.held_gained)
      put.addWidget(button("Leave", lambda: self.leave_selected(), "Leave a record in the selected slot"))
      put.addWidget(button("Take back", lambda: self.take_back_selected(), "Empty the selected slot"))
      result = QtWidgets.QHBoxLayout()
      result.addWidget(QtWidgets.QLabel("Waiting result"))
      result.addWidget(self.result_species, 1)
      result.addWidget(self.result_egg)
      result.addWidget(self.result_hatch)
      lay = QtWidgets.QVBoxLayout(box)
      lay.addWidget(self.held)
      lay.addLayout(put)
      lay.addLayout(result)
      return box

   def _fill_nursery(self) -> None:
      """!Shows the nursery's slots and the waiting result (B2).
      @return None
      """
      doc = self.battle_doc()
      slots = nursery_model.slot_count(doc) if doc is not None else 0
      held = {b.get(nursery_model.SLOT_KEY): b for b in nursery_model.held_of(self.save)} \
         if self.save is not None else {}
      species = [str(e.get("name")) for e in battle.entries(doc, "species") if isinstance(e, dict)] \
         if doc is not None else []
      was = self._filling
      self._filling = True
      try:
         self.held.setRowCount(slots)
         for r in range(slots):
            b = held.get(r)
            texts = {HELD_SLOT_COLUMN: str(r),
                     HELD_SPECIES_COLUMN: str(b.get(nursery_model.SPECIES_KEY)) if b else EMPTY_SLOT,
                     HELD_LEVEL_COLUMN: str(b.get(nursery_model.LEVEL_KEY)) if b else "",
                     HELD_GAINED_COLUMN: str(b.get(nursery_model.GAINED_KEY, 0)) if b else ""}
            for c, text in texts.items():
               self.held.setItem(r, c, QtWidgets.QTableWidgetItem(text))
         self.held.resizeColumnsToContents()
         set_combo(self.held_species, species, self.held_species.currentText() or (species[0] if species else None))
         result = nursery_model.result_of(self.save) if self.save is not None else None
         set_combo(self.result_species, [NONE_TEXT] + species,
                   result.get(nursery_model.SPECIES_KEY) if result is not None else NONE_TEXT)
         eggs = doc is not None and nursery_model.eggs(doc) is not None
         set_spin_max(self.result_hatch, nursery_model.counter_max(doc) if eggs else 0)
         is_egg = result is not None and nursery_model.HATCH_KEY in result
         set_check(self.result_egg, is_egg)
         self.result_hatch.blockSignals(True)
         self.result_hatch.setValue(int(result[nursery_model.HATCH_KEY]) if is_egg else 0)
         self.result_hatch.blockSignals(False)
         on = self.save is not None and slots > 0
         for w in (self.held, self.held_species, self.held_level, self.held_gained, self.result_species):
            set_enabled(w, on)   # tables go read-only and keep their scroll bars (also below)
         self.result_egg.setEnabled(on and eggs)
         self.result_hatch.setEnabled(on and eggs and is_egg)
      finally:
         self._filling = was

   def _build_steps(self) -> QtWidgets.QGroupBox:
      """!Builds the Step counters box (F3): each step effect with the save's counter, and the Set row.
      @return the box
      """
      ## The step effects with the save's counters.
      self.steps = QtWidgets.QTableWidget(0, len(STEP_COLUMNS))
      self.steps.setHorizontalHeaderLabels(STEP_COLUMNS)
      self.steps.verticalHeader().setVisible(False)
      self.steps.horizontalHeader().setStretchLastSection(True)
      self.steps.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.steps.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      ## The steps to set the selected counter to.
      self.step_count = QtWidgets.QSpinBox()
      self.step_count.setRange(0, step_model.max_every() - 1)
      box = QtWidgets.QGroupBox("Step counters (steps counted towards each step effect's next run)")
      row = QtWidgets.QHBoxLayout()
      row.addStretch(1)
      row.addWidget(QtWidgets.QLabel("Counted"))
      row.addWidget(self.step_count)
      row.addWidget(button("Set", lambda: self.set_step_selected(self.step_count.value()),
                           "Set the selected step effect's counter (exported into the script banks)"))
      lay = QtWidgets.QVBoxLayout(box)
      lay.addWidget(self.steps)
      lay.addLayout(row)
      return box

   def _fill_steps(self) -> None:
      """!Shows the step effects with the save's counters (F3).
      @return None
      """
      doc = self.battle_doc()
      rows = step_model.counter_rows(self.save, doc) if self.save is not None and doc is not None else []
      self.steps.setRowCount(len(rows))
      for r, (name, counted, every) in enumerate(rows):
         texts = {STEP_NAME_COLUMN: name, STEP_COUNT_COLUMN: str(counted), STEP_EVERY_COLUMN: str(every),
                  STEP_LEFT_COLUMN: str(max(every - counted, 0))}
         for c, text in texts.items():
            self.steps.setItem(r, c, QtWidgets.QTableWidgetItem(text))
      self.steps.resizeColumnsToContents()
      on = self.save is not None and bool(rows)
      for w in (self.steps, self.step_count):
         set_enabled(w, on)

   def set_step_selected(self, steps: int) -> bool:
      """!Sets the selected step effect's counter.
      @param steps  0 to every - 1
      @return True when set
      """
      row = self.steps.currentRow()
      item = self.steps.item(row, STEP_NAME_COLUMN) if row >= 0 else None
      if item is None:
         return False
      name = item.text()
      return self._change("Step counter", lambda save, doc: step_model.set_counter(save, doc, name, steps))

   def _build_game(self) -> QtWidgets.QGroupBox:
      """!S5: builds the Game box (engine N3): the game block's version, size and bytes, From a save file, Remove.
      @return the box
      """
      ## The game's version of its block.
      self.game_version = QtWidgets.QSpinBox()
      self.game_version.setRange(0, game_block.MAX_VERSION)
      self.game_version.setToolTip("The version the game passes in its save::GameBlock (another one: not loaded)")
      ## The block's size.
      self.game_size = QtWidgets.QSpinBox()
      self.game_size.setRange(1, MAX_BLOCK_SPIN)
      self.game_size.setToolTip("The game's game_block_bytes() (another size: not loaded)")
      ## The block's bytes as hex.
      self.game_hex = QtWidgets.QPlainTextEdit()
      self.game_hex.setPlaceholderText("hex bytes (the rest of the block is zeros)")
      self.game_hex.setMaximumHeight(self.fontMetrics().height() * GAME_HEX_ROWS)
      ## The block in a line.
      self.game_info = QtWidgets.QLabel()
      box = QtWidgets.QGroupBox("Game block (the image's Game section: the game's own save data)")
      row = QtWidgets.QHBoxLayout()
      row.addWidget(QtWidgets.QLabel("Version"))
      row.addWidget(self.game_version)
      row.addWidget(QtWidgets.QLabel("Size"))
      row.addWidget(self.game_size)
      row.addWidget(button("Apply", lambda: self.set_game_from_form(), "Write the version, size and bytes"))
      row.addWidget(button("From a save file...", lambda: self.game_from_file(),
                           "Take the Game section of a save the game wrote"))
      row.addWidget(button("Remove", lambda: self._change("No game block", lambda save, _d:
                                                                game_block.clear_game(save)),
                           "The image has no Game section"))
      row.addStretch(1)
      lay = QtWidgets.QVBoxLayout(box)
      lay.addLayout(row)
      lay.addWidget(self.game_hex)
      lay.addWidget(self.game_info)
      box.setVisible(game_block.available())
      ## The box (hidden for an engine without the Game section).
      self.game_box = box
      return box

   def _fill_game(self) -> None:
      """!S5: shows the test save's game block.
      @return None
      """
      g = game_block.game_of(self.save) if self.save is not None else None
      self.game_box.setVisible(game_block.available())
      self.game_version.setValue(int(g.get(game_block.VERSION_KEY, 0)) if g else 0)
      self.game_size.setValue(int(g.get(game_block.SIZE_KEY, 1)) if g else 1)
      try:
         rows = game_block.hex_rows(self.save) if g else []
         info = "; ".join(game_block.lines(self.save)) if g else "(no game block: the image has no Game section)"
      except DocumentError as e:
         rows, info = [], str(e)
      self.game_hex.setPlainText("\n".join(r for _o, r in rows))
      self.game_info.setText(info)
      for w in (self.game_version, self.game_size, self.game_hex):
         set_enabled(w, self.save is not None)

   def set_game_from_form(self) -> bool:
      """!S5: writes the Game box's version, size and bytes.
      @return True when it went through
      """
      text = "".join(self.game_hex.toPlainText().split())
      try:
         data = bytes.fromhex(text)
      except ValueError:
         report_failure(self, "Game block", "the bytes are hex digits, two per byte")
         return False
      version, size = self.game_version.value(), self.game_size.value()
      return self._change("Game block", lambda save, _d: game_block.set_game(save, version, size, data))

   def game_from_file(self, path: str | Path | None = None) -> bool:
      """!S5: takes the Game section of a save file the game wrote.
      @param path  the file, or None to ask
      @return True when it went through
      """
      if path is None:
         path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Game block from a save file", "", SAVE_FILE_FILTER)
         if not path:
            return False
      return self._change("Game block from a save", lambda save, _d: game_block.from_image(save, path))

   def _build_shapes(self) -> QtWidgets.QGroupBox:
      """!Builds the Save shapes box (C6): the game's script sub-banks' shapes, whether the save history holds
      them, and the Record button.
      @return the box
      """
      ## The shapes as text.
      self.shapes = QtWidgets.QLabel()
      self.shapes.setWordWrap(True)
      box = QtWidgets.QGroupBox("Save shapes (script banks)")
      lay = QtWidgets.QVBoxLayout(box)
      lay.addWidget(self.shapes)
      lay.addWidget(button("Record shapes", lambda: self.record_shapes(),
                           "Add the shapes the save history lacks: older saves keep loading after flags or "
                           "variables change"))
      return box

   def _fill_shapes(self) -> None:
      """!Shows the game's save shapes (C6).
      @return None
      """
      p = self.project()
      manifest = p.scripts_manifest() if p is not None else None
      if manifest is None:
         self.shapes.setText("(the game has no scripts manifest: no script banks in its save)")
         return
      try:
         self.shapes.setText("\n".join(save_shapes.lines(manifest)) or "(no script storage)")
      except (DocumentError, OSError, ValueError) as e:
         self.shapes.setText(str(e))

   def record_shapes(self) -> int:
      """!Records the game's save shapes in its save history (C6).
      @return shapes added (-1: refused)
      """
      p = self.project()
      manifest = p.scripts_manifest() if p is not None else None
      if manifest is None:
         return -1
      try:
         n = save_shapes.record(manifest)
      except (DocumentError, OSError, ValueError) as e:
         report_failure(self, "Record save shapes", str(e))
         return -1
      self.host.show_status(f"save history: {n} shapes added")
      self._fill_shapes()
      return n

   # -- reading -------------------------------------------------------------------------------------------------------

   def save_names(self) -> list[str]:
      """!The game's test saves by name.
      @return stems
      """
      p = self.project()
      return [path.stem for path in inventory.testsave_paths(p)] if p is not None else []

   def pocket_items(self, pocket: str) -> list[str]:
      """!The items whose pocket is this one (what Put offers).
      @param pocket  pocket name
      @return item names
      """
      doc = self.battle_doc()
      if doc is None:
         return []
      return [str(e.get("name")) for e in battle.entries(doc, "items") if isinstance(e, dict) and
              e.get(inventory.POCKET_KEY) == pocket]

   def refresh(self) -> None:
      """!Re-reads the saves, the pockets and the shown pocket's slots.
      @return None
      """
      doc = self.battle_doc()
      saves = self.save_names()
      if self.save is not None and self.save.path is not None and self.save.path.stem not in saves:
         self.save = None
      if self.save is None and saves:
         self.save = inventory.open_testsave(self.project(), saves[0])
      names = pocket_model.pocket_names(doc)
      self.pocket = self.pocket if self.pocket in names else (names[0] if names else None)
      self._filling = True
      try:
         set_combo(self.saves, saves, self.save.path.stem if self.save is not None else None)
         set_combo(self.pockets, names, self.pocket)
         self._fill_pocket()
      finally:
         self._filling = False
      self._fill_boxes()
      self._fill_steps()
      self._fill_nursery()
      self._fill_game()
      self._fill_shapes()
      set_enabled(self, doc is not None)
      self.show_errors()

   def _fill_boxes(self) -> None:
      """!Shows the boxes, the current box and the boxed creatures (G3).
      @return None
      """
      doc = self.battle_doc()
      names = storage_model.box_names(doc) if doc is not None else []
      boxed = storage_model.boxed_of(self.save) if self.save is not None else []
      size = storage_model.section(doc)[storage_model.SIZE_KEY] if doc is not None else 0
      was = self._filling
      self._filling = True
      try:
         current = storage_model.current_box(self.save) if self.save is not None else 0
         set_combo(self.current, names, names[current] if current < len(names) else None)
         self.boxed.setRowCount(len(boxed))
         for r, b in enumerate(boxed):
            slot = b.get(storage_model.BOXED_SLOT)
            box = slot // size if isinstance(slot, int) and size else 0
            texts = {SLOT_COLUMN: str(slot), BOX_COLUMN: names[box] if box < len(names) else str(box),
                     SPECIES_COLUMN: str(b.get(storage_model.BOXED_SPECIES)),
                     LEVEL_COLUMN: str(b.get(storage_model.BOXED_LEVEL)),
                     EGG_COLUMN: str(b[nursery_model.HATCH_KEY]) if nursery_model.HATCH_KEY in b else ""}
            for c, text in texts.items():
               self.boxed.setItem(r, c, QtWidgets.QTableWidgetItem(text))
         self.boxed.resizeColumnsToContents()
         species = [str(e.get("name")) for e in battle.entries(doc, "species") if isinstance(e, dict)] \
            if doc is not None else []
         set_combo(self.species_choice, species, self.species_choice.currentText() or
                   (species[0] if species else None))
         if doc is not None:
            set_spin_max(self.level, storage_model.max_level(doc))
         on = self.save is not None and bool(names)
         for w in (self.current, self.boxed, self.species_choice, self.level):
            set_enabled(w, on)
         eggs = doc is not None and nursery_model.eggs(doc) is not None
         set_spin_max(self.box_hatch, nursery_model.counter_max(doc) if eggs else 0)
         for w in (self.box_hatch, self.egg_button, self.not_egg_button):
            w.setEnabled(on and eggs)
      finally:
         self._filling = was

   def _fill_pocket(self) -> None:
      """!Shows the pocket's slots, its items to put and the save's problems.
      @return None
      """
      doc = self.battle_doc()
      bag = inventory.bag_of(self.save) if self.save is not None else {}
      slots = bag.get(self.pocket, []) if self.pocket is not None else []
      self.table.setRowCount(len(slots))
      for r, s in enumerate(slots):
         self.table.setItem(r, ITEM_COLUMN, QtWidgets.QTableWidgetItem(str(s.get(inventory.SLOT_ITEM))))
         self.table.setItem(r, COUNT_COLUMN, QtWidgets.QTableWidgetItem(str(s.get(inventory.SLOT_COUNT))))
      self.table.resizeColumnsToContents()
      items = self.pocket_items(self.pocket) if self.pocket is not None else []
      set_combo(self.item_choice, items, items[0] if items else None)
      row = next((p for p in pocket_model.rows(doc) if p["name"] == self.pocket), None) if doc is not None else None
      self.pocket_info.setText(f"{len(slots)}/{row['capacity']} slots, up to {row['quantity_max']} each"
                               if row is not None else "")
      if row is not None:
         set_spin_max(self.count, row["quantity_max"])
      on = self.save is not None
      for w in (self.item_choice, self.count, self.table):
         set_enabled(w, on)
      if self.save is None or doc is None:
         self.problems.setText("No test save: New... makes one." if doc is not None else "")
         self.problems.setStyleSheet("")
         return
      problems = inventory.check(self.save, doc)
      self.problems.setText("; ".join(problems) if problems else "The bag fits the battle data.")
      self.problems.setStyleSheet(f"color: {PROBLEM_COLOR if problems else OK_COLOR};")

   # -- editing (the test save is its own file: saved after each change) ----------------------------------------------

   def open_save(self, name: str) -> bool:
      """!Opens a test save by name.
      @param name  its stem
      @return True when open
      """
      p = self.project()
      if p is None or not name:
         return False
      try:
         self.save = inventory.open_testsave(p, name)
      except (DocumentError, OSError, ValueError) as e:
         report_failure(self, "Open test save", str(e))
         return False
      self.refresh()
      return True

   def show_pocket(self, name: str) -> None:
      """!Shows another pocket.
      @param name  pocket name
      @return None
      """
      self.pocket = name or None
      self._filling = True
      try:
         self._fill_pocket()
      finally:
         self._filling = False

   def new_save(self, name: str | None = None) -> bool:
      """!Makes an empty test save and opens it.
      @param name  its name, or None to ask
      @return True when made
      """
      p = self.project()
      if p is None:
         return False
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, "New test save", "Name:")
         if not ok:
            return False
      try:
         self.save = inventory.new_testsave(p, name)
      except (DocumentError, OSError) as e:
         report_failure(self, "New test save", str(e))
         return False
      self.refresh()
      return True

   def _change(self, label: str, fn: Any) -> bool:
      """!One change of the test save, saved at once.
      @param label  what it is (messages)
      @param fn     callable(save, battle doc)
      @return True when it went through
      """
      doc, save = self.battle_doc(), self.save
      if doc is None or save is None:
         return False
      try:
         with save.edit(label):
            fn(save, doc)
         save.save()
      except (DocumentError, OSError, ValueError) as e:
         report_failure(self, label, str(e))
         self.host.show_status(f"{label}: {e}")
         return False
      self.refresh()
      return True

   def put(self, item: str, count: int) -> bool:
      """!Puts items into the save's bag (their own pocket).
      @param item   item name
      @param count  how many
      @return True when added
      """
      if not item:
         return False
      return self._change("Put items", lambda save, doc: inventory.put(save, doc, item, count))

   def take_selected(self, count: int | None = None) -> bool:
      """!Takes items of the selected slot out of the save's bag.
      @param count  how many, or None for all
      @return True when taken
      """
      row = self.table.currentRow()
      bag = inventory.bag_of(self.save) if self.save is not None else {}
      slots = bag.get(self.pocket, []) if self.pocket is not None else []
      if not 0 <= row < len(slots):
         return False
      item = str(slots[row].get(inventory.SLOT_ITEM))
      return self._change("Take items", lambda save, doc: inventory.take(save, doc, item, count))

   def box_creature(self, species: str, level: int) -> bool:
      """!Boxes a creature (the current box's first free slot, else any).
      @param species  species name
      @param level    its level
      @return True when boxed
      """
      if not species:
         return False
      return self._change("Box creature", lambda save, doc: storage_model.put_creature(save, doc, species, level))

   def unbox_selected(self) -> bool:
      """!Takes the selected boxed creature out.
      @return True when taken
      """
      row = self.boxed.currentRow()
      boxed = storage_model.boxed_of(self.save) if self.save is not None else []
      if not 0 <= row < len(boxed):
         return False
      slot = boxed[row].get(storage_model.BOXED_SLOT)
      return self._change("Unbox creature", lambda save, _doc: storage_model.remove_creature(save, slot))

   def set_boxed_egg(self, steps: int | None) -> bool:
      """!Makes the selected boxed creature an egg, or a creature again (B2).
      @param steps  its hatch counter, or None: not an egg
      @return True when it went through
      """
      row = self.boxed.currentRow()
      boxed = storage_model.boxed_of(self.save) if self.save is not None else []
      if not 0 <= row < len(boxed):
         return False
      slot = boxed[row].get(storage_model.BOXED_SLOT)
      return self._change("Boxed egg", lambda save, doc: nursery_model.set_boxed_hatch(save, doc, slot, steps))

   def leave_selected(self) -> bool:
      """!Leaves the form's record in the selected nursery slot (B2).
      @return True when it went through
      """
      slot = self.held.currentRow()
      species = self.held_species.currentText()
      if slot < 0 or not species:
         return False
      level, gained = self.held_level.value(), self.held_gained.value()
      return self._change("Nursery slot", lambda save, doc: nursery_model.put_held(save, doc, slot, species, level,
                                                                                   gained))

   def take_back_selected(self) -> bool:
      """!Empties the selected nursery slot (B2).
      @return True when it went through
      """
      slot = self.held.currentRow()
      held = {b.get(nursery_model.SLOT_KEY) for b in nursery_model.held_of(self.save)} if self.save else set()
      if slot not in held:
         return False
      return self._change("Nursery slot", lambda save, _doc: nursery_model.take_held(save, slot))

   def set_result_from_form(self) -> bool:
      """!Writes the waiting result the form shows (B2: "(none)": nothing waits).
      @return True when it went through
      """
      if self._filling:
         return False
      text = self.result_species.currentText()
      species = None if text in (NONE_TEXT, "") else text
      hatch = self.result_hatch.value() if self.result_egg.isChecked() else None
      return self._change("Nursery result", lambda save, doc: nursery_model.set_result(save, doc, species, hatch))

   def set_current_box(self, box: int) -> bool:
      """!Sets the current box.
      @param box  box index
      @return True when set
      """
      if self._filling:
         return False
      return self._change("Current box", lambda save, doc: storage_model.set_current_box(save, doc, box))

   def export_save(self, out: str | Path | None = None) -> bool:
      """!Writes the engine save image of the bag.
      @param out  the file, or None to ask
      @return True when written
      """
      p = self.project()
      if p is None or self.save is None:
         return False
      if out is None:
         out, _filter = QtWidgets.QFileDialog.getSaveFileName(self, "Export save image", "", IMAGE_FILTER)
         if not out:
            return False
      try:
         n = inventory.export(self.save, p, out)
      except (DocumentError, OSError) as e:
         report_failure(self, "Export save image", str(e))
         return False
      self.host.show_status(f"wrote {out} ({n} B)")
      return True
