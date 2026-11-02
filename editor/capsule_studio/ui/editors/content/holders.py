"""!The Passives / Items panel (§3.1 Content): the battle manifest's
passives and items, one tab each (titled in the game's words), and the shop
lists (a Shops tab).

Each tab lists its entries (new / copy / rename / delete / up / down: the
shared EntryPanel; a rename follows species, party members and the effect
logic) next to a form: whether the battle shows the entry when its logic
announces it, its manifest point handlers (core.holders: the ruleset points
its kind may handle) and what names it. "Logic..." shows its `.ceffect`
owner on Logic > Effects. An item also has its bag and use fields (
core.inventory: pocket, price, use, target, key / consumed / holdable) and
its use logic (the use_field / use_battle handlers as text; Add writes a
stub handler). Recruit makes the item recruit the battler it is used on
(`recruit holder BONUS;` in its use_battle handler, battle use, a battler
target; the rules are Structure > Recruit). F1: Start makes its use_field
handler start a timed field effect (`field_effect start NAME N;`, the effects
are Structure > Field effects). Every change is one undo step;
the compile result shows at the bottom of each tab.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6 import QtWidgets

from ....core import battle, holders, inventory
from ....core.structure import field_effects as fx_model
from ....core.structure import pockets as pocket_model
from ....core.structure import recruit as recruit_model
from ...panes import split_box
from ...widgets import button, set_enabled
from ..battle_common import BattlePanel, EntryPanel, combo, set_check, set_combo, set_spin, spin
from ..record_widgets import PointHandlersBox

if TYPE_CHECKING:
   from ...panel import PanelHost

## The pocket combo's entry for no pocket.
NO_POCKET = "(none)"
## The flag boxes: (field, text, tool tip).
FLAG_BOXES = [(inventory.KEY_KEY, "Key item", "Never consumed or sold"),
              (inventory.CONSUMED_KEY, "Consumed", "A use with an effect takes one from the bag"),
              (inventory.HOLDABLE_KEY, "Holdable", "A party member may hold it"),
              (inventory.EGGS_KEY, "Usable on eggs", "it may be used on an egg (refused by default)")]
## Lowest height of the use logic text, pixels.
USE_TEXT_HEIGHT = 140
## Bonus the Recruit row starts at for an item that does not recruit yet (the neutral pipeline's percent: x1).
NEW_RECRUIT_BONUS = 10


class HolderTab(EntryPanel):
   """!One holder list: the entries and the form of the selected one (subclasses set ``kind``)."""

   def build_form(self, layout: QtWidgets.QVBoxLayout) -> None:
      """!Adds the announce box, the point handlers, the uses and the Logic... button.
      @param layout  QVBoxLayout to add to
      @return None
      """
      ## Shown when its logic says `announce;`.
      self.announce = QtWidgets.QCheckBox("Announced (the battle shows it when its logic says announce;)")
      self.announce.clicked.connect(lambda on: self.set_announce(bool(on)))
      layout.addWidget(self.announce)
      ## Its manifest point handlers.
      self.handlers = PointHandlersBox(lambda label, fn: self.edit(label, fn), lambda: self.battle_doc())
      layout.addWidget(self.handlers)
      ## What names it.
      self.used_by = QtWidgets.QLabel()
      self.used_by.setWordWrap(True)
      layout.addWidget(self.used_by)
      ## Shows its owner on Logic > Effects.
      self.logic_button = button("Logic...", lambda: self.open_logic(), "Show its .ceffect logic on Logic > Effects")
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.logic_button)
      row.addStretch(1)
      layout.addLayout(row)

   def fill_form(self, entry: dict[str, Any] | None) -> None:
      """!Shows an entry.
      @param entry  dict, or None
      @return None
      """
      doc, p = self.battle_doc(), self.project()
      on = entry is not None
      for w in (self.announce, self.logic_button):
         w.setEnabled(on)
      set_check(self.announce, on and entry.get(holders.ANNOUNCE_KEY, True) is not False)
      if not on or doc is None:
         self.handlers.show_handlers(None, [], [])
         self.used_by.setText("")
         return
      name = entry.get("name")
      kind = self.kind   # a local name: Doxygen 1.12 misreads the inherited class member here
      self.handlers.show_handlers((kind, name), holders.handlers(doc, kind, name),
                                  holders.point_choices(p, kind) if p is not None else [])
      row = next((r for r in holders.holder_rows(doc, kind) if r["name"] == name), None)
      users = row["uses"] if row is not None else []
      self.used_by.setText("Named by: " + (", ".join(users) if users else "nothing"))

   def set_announce(self, on: bool) -> bool:
      """!Sets the selected entry's announce flag (one undo step).
      @param on  announced
      @return True when the edit went through
      """
      doc, kind, name = self.battle_doc(), self.kind, self.selected
      if self._filling or doc is None or name is None:
         return False
      return self.edit("Announce", lambda: holders.set_announce(doc, kind, name, on))

   def open_logic(self) -> bool:
      """!Shows the selected entry's owner on Logic > Effects.
      @return True when the Effects page shows it
      """
      if self.selected is None:
         return False
      # the owner kind of the list (the effect language's word: core.holders.handler_lists())
      return super().open_logic(f"{holders.handler_lists()[self.kind]}:{self.selected}")


class PassivesTab(HolderTab):
   """!The passives."""

   ## See EntryPanel.kind.
   kind = "passives"


class ItemsTab(HolderTab):
   """!The items: the holder form, then the bag box (pocket, price, use, target, key / consumed / holdable;
   choices from the engine's lists and the structure's pockets) and the use logic box (the item's use_field /
   use_battle handlers as text, Add buttons writing a stub handler)."""

   ## See EntryPanel.kind.
   kind = "items"
   ## See EntryPanel.scroll_form: the bag and use logic boxes make the form taller than a small window (an F1
   ## leftover: the use logic's Add buttons were drawn over its text).
   scroll_form = True

   def build_form(self, layout: QtWidgets.QVBoxLayout) -> None:
      """!Adds the holder form, the bag box and the use logic box.
      @param layout  QVBoxLayout to add to
      @return None
      """
      super().build_form(layout)
      bag = QtWidgets.QGroupBox("Bag and use")
      form = QtWidgets.QFormLayout(bag)
      ## The item's pocket ("(none)": it cannot go into the bag).
      self.pocket = combo(lambda text: self.set_field(inventory.POCKET_KEY, None if text == NO_POCKET else text))
      ## Its price in a shop.
      self.price = spin(0, inventory.max_price(), lambda v: self.set_field(inventory.PRICE_KEY, v))
      ## Where it can be used.
      self.use = combo(lambda text: self.set_field(inventory.USE_KEY, text))
      ## What it is used on.
      self.target = combo(lambda text: self.set_field(inventory.TARGET_KEY, text))
      ## The flags (key, consumed, holdable).
      self.flags = {}
      flag_row = QtWidgets.QHBoxLayout()
      for field, text, tip in FLAG_BOXES:
         box = QtWidgets.QCheckBox(text)
         box.setToolTip(tip)
         box.clicked.connect(lambda on, f=field: self.set_field(f, bool(on)))
         self.flags[field] = box
         flag_row.addWidget(box)
      flag_row.addStretch(1)
      form.addRow("Pocket", self.pocket)
      form.addRow("Price", self.price)
      form.addRow("Use", self.use)
      form.addRow("Target", self.target)
      form.addRow(flag_row)
      layout.addWidget(bag)
      logic_box = QtWidgets.QGroupBox("Use logic")
      lay = QtWidgets.QVBoxLayout(logic_box)
      ## The item's use handlers as text (edited on Logic > Effects).
      self.use_text = QtWidgets.QPlainTextEdit()
      self.use_text.setReadOnly(True)
      self.use_text.setMinimumHeight(USE_TEXT_HEIGHT)
      lay.addWidget(self.use_text)
      row = QtWidgets.QHBoxLayout()
      ## Buttons adding a stub handler, by hook.
      self.add_hook = {}
      for hook in inventory.use_hooks().values():
         b = button(f"Add {hook}", lambda h=hook: self.add_use(h),
                    f"Write `on {hook} {{ fail; }}` into the item's logic (its use grows to cover it)")
         self.add_hook[hook] = b
         row.addWidget(b)
      row.addStretch(1)
      lay.addLayout(row)
      # The recruit row (core.structure.recruit)
      recruit_row = QtWidgets.QHBoxLayout()
      ## The bonus Recruit passes recruit_odds.
      self.recruit_bonus = QtWidgets.QSpinBox()
      self.recruit_bonus.setRange(0, recruit_model.max_bonus())
      self.recruit_bonus.setToolTip("The bonus the item passes the ruleset's recruit_odds pipeline")
      ## Writes `recruit holder BONUS;`.
      self.recruit_button = button("Recruit", lambda: self.set_recruit(self.recruit_bonus.value()),
                                   "The item recruits the battler it is used on (use_battle; battle use, target "
                                   "battler)")
      ## Whether the item recruits, and with which bonus.
      self.recruit_info = QtWidgets.QLabel()
      recruit_row.addWidget(QtWidgets.QLabel("Recruit bonus"))
      recruit_row.addWidget(self.recruit_bonus)
      recruit_row.addWidget(self.recruit_button)
      recruit_row.addWidget(self.recruit_info, 1)
      lay.addLayout(recruit_row)
      # F1: the field effect row (core.structure.field_effects)
      field_row = QtWidgets.QHBoxLayout()
      ## The field effect Start names (the structure's).
      self.field_effect = QtWidgets.QComboBox()
      ## Its steps or minutes.
      self.field_amount = QtWidgets.QSpinBox()
      self.field_amount.setRange(1, fx_model.max_amount())
      ## Writes `field_effect start NAME N;`.
      self.field_button = button("Start", lambda: self.set_field_effect(self.field_effect.currentText(),
                                                                         self.field_amount.value()),
                                 "The item's use_field logic starts the field effect (field use)")
      ## Which effect the item starts.
      self.field_info = QtWidgets.QLabel()
      field_row.addWidget(QtWidgets.QLabel("Field effect"))
      field_row.addWidget(self.field_effect)
      field_row.addWidget(self.field_amount)
      field_row.addWidget(self.field_button)
      field_row.addWidget(self.field_info, 1)
      lay.addLayout(field_row)
      layout.addWidget(logic_box)

   def fill_form(self, entry: dict[str, Any] | None) -> None:
      """!Shows an entry, its bag fields and its use logic.
      @param entry  dict, or None
      @return None
      """
      super().fill_form(entry)
      doc, p = self.battle_doc(), self.project()
      on = entry is not None and doc is not None
      for w in (self.pocket, self.price, self.use, self.target, self.use_text, *self.flags.values(),
                *self.add_hook.values(), self.recruit_bonus, self.recruit_button, self.field_effect,
                self.field_amount, self.field_button):
         set_enabled(w, on)   # the use text goes read-only and keeps its scroll bars
      if not on:
         self.use_text.setPlainText("")
         self.recruit_info.setText("")
         self.field_info.setText("")
         return
      name = entry.get("name")
      f = inventory.fields_of(doc, name)
      set_combo(self.pocket, [NO_POCKET] + pocket_model.pocket_names(doc), f[inventory.POCKET_KEY] or NO_POCKET)
      set_spin(self.price, f[inventory.PRICE_KEY])
      set_combo(self.use, inventory.uses(), f[inventory.USE_KEY])
      set_combo(self.target, inventory.targets(), f[inventory.TARGET_KEY])
      for field, box in self.flags.items():
         set_check(box, f[field])
      logic_texts = inventory.use_logic(p, name) if p is not None else {}
      shown = []
      for hook, text in logic_texts.items():
         self.add_hook[hook].setEnabled(text is None)
         shown.append(text if text is not None else f"# no `on {hook}` handler")
      needed = inventory.hooks_needed(f[inventory.USE_KEY])
      head = f"# use {f[inventory.USE_KEY]}: " + (", ".join(f"on {h}" for h in needed) if needed else "no use logic")
      self.use_text.setPlainText("\n\n".join([head] + shown))
      bonus = recruit_model.recruit_bonus(p, name) if p is not None else None
      stated = recruit_model.is_stated(doc)
      if bonus is None:
         self.recruit_info.setText("does not recruit" + ("" if stated else " (no recruit rules: Structure > Recruit)"))
         set_spin(self.recruit_bonus, NEW_RECRUIT_BONUS)
      else:
         self.recruit_info.setText(f"recruits with bonus {bonus}" +
                                   ("" if stated else " (no recruit rules yet: Structure > Recruit)"))
         if bonus.isdigit():
            set_spin(self.recruit_bonus, int(bonus))
      names = fx_model.effect_names(doc)
      started = fx_model.item_field_effect(p, name) if p is not None else None
      set_combo(self.field_effect, names, started[0] if started is not None else (names[0] if names else ""))
      set_spin(self.field_amount, int(started[1]) if started is not None and started[1].isdigit()
               else fx_model.DEFAULT_AMOUNT)
      for w in (self.field_effect, self.field_amount, self.field_button):
         w.setEnabled(bool(names))
      units = {r["name"]: r["unit"] for r in fx_model.effect_rows(doc)}
      self.field_info.setText(f"starts {started[0]} for {started[1]} {units.get(started[0], '')}".rstrip()
                              if started is not None else
                              ("starts none" if names else "no field effects (Structure > Field effects)"))

   def set_field(self, field: str, value: Any) -> bool:
      """!Sets one of the selected item's bag fields (one undo step; a use needing a hook gets a stub handler).
      @param field  core.inventory field
      @param value  the value
      @return True when the edit went through
      """
      doc, name = self.battle_doc(), self.selected
      if self._filling or doc is None or name is None:
         return False
      ok = self.edit(f"Item {field}", lambda: inventory.set_item_field(doc, name, field, value))
      if not ok:
         self.host.changed()
      return ok

   def set_recruit(self, bonus: int) -> bool:
      """!Makes the selected item recruit with a bonus (one undo step: use, target and logic).
      @param bonus  the bonus passed to recruit_odds
      @return True when the edit went through
      """
      p, name = self.project(), self.selected
      if p is None or name is None:
         return False
      ok = self.edit("Recruit logic", lambda: recruit_model.set_recruit_logic(p, name, bonus))
      if not ok:
         self.host.changed()
      return ok

   def set_field_effect(self, effect: str, amount: int) -> bool:
      """!Makes the selected item's use_field logic start a field effect (one undo step).
      @param effect  a field effect of the structure
      @param amount  its steps or minutes
      @return True when the edit went through
      """
      p, name = self.project(), self.selected
      if p is None or name is None or not effect:
         return False
      ok = self.edit("Item field effect", lambda: fx_model.set_item_field_effect(p, name, effect, amount))
      if not ok:
         self.host.changed()
      return ok

   def add_use(self, hook: str) -> bool:
      """!Adds a stub use handler to the selected item.
      @param hook  use_field or use_battle
      @return True when the edit went through
      """
      p, name = self.project(), self.selected
      if p is None or name is None:
         return False
      return self.edit("Add use logic", lambda: inventory.add_use_handler(p, name, hook))


class ShopsTab(BattlePanel):
   """!The shop lists: the shops and the items each sells (an item needs a price and a pocket).

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## See EditorPanel.panel_id.
   panel_id = "shops"
   ## See EditorPanel.title.
   title = "Shops"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the shop list, its items and the buttons.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The selected shop, or None.
      self.selected = None
      ## The shops.
      self.shop_list = QtWidgets.QListWidget()
      self.shop_list.currentRowChanged.connect(lambda row: self._shop_chosen(row))
      ## The selected shop's items.
      self.item_list = QtWidgets.QListWidget()
      ## The item to add.
      self.item_choice = QtWidgets.QComboBox()
      left = QtWidgets.QVBoxLayout()
      left.addWidget(QtWidgets.QLabel("Shops"))
      left.addWidget(self.shop_list, 1)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("New...", lambda: self.add_shop()))
      row.addWidget(button("Rename...", lambda: self.rename_shop()))
      row.addWidget(button("Delete", lambda: self.remove_shop()))
      left.addLayout(row)
      right = QtWidgets.QVBoxLayout()
      right.addWidget(QtWidgets.QLabel("Sells (at the items' prices)"))
      right.addWidget(self.item_list, 1)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.item_choice, 1)
      row.addWidget(button("Add", lambda: self.add_item(self.item_choice.currentText())))
      row.addWidget(button("Remove", lambda: self.remove_item()))
      right.addLayout(row)
      right.addWidget(self.errors)
      lay = QtWidgets.QHBoxLayout(self)
      for part in (left, right):
         box = QtWidgets.QWidget()
         box.setLayout(part)
         lay.addWidget(box, 1)
      split_box(lay)   # [RZ] shops | what they sell

   def refresh(self) -> None:
      """!Re-reads the shops.
      @return None
      """
      doc = self.battle_doc()
      rows = inventory.shops(doc) if doc is not None else []
      names = [r["name"] for r in rows]
      chosen = self.selected
      chosen = chosen if chosen in names else (names[0] if names else None)
      self.selected = chosen
      self._filling = True
      try:
         self.shop_list.clear()
         self.shop_list.addItems(names)
         if chosen is not None:
            self.shop_list.setCurrentRow(names.index(chosen))
         self._fill_items(rows)
         items = [i.get("name") for i in battle.entries(doc, "items")] if doc is not None else []
         set_combo(self.item_choice, [str(i) for i in items], items[0] if items else None)
      finally:
         self._filling = False
      set_enabled(self, doc is not None)
      self.show_errors()

   def _fill_items(self, rows: list[dict[str, Any]]) -> None:
      """!Shows the selected shop's items with their prices.
      @param rows  inventory.shops()
      @return None
      """
      doc = self.battle_doc()
      self.item_list.clear()
      shop = next((r for r in rows if r["name"] == self.selected), None)
      for item in shop[inventory.SHOP_ITEMS_KEY] if shop is not None else []:
         try:
            price = inventory.fields_of(doc, item)[inventory.PRICE_KEY]
         except Exception:   # an item the shop names that is gone: the compile line says so
            price = "?"
         self.item_list.addItem(f"{item}  {price}")

   def _shop_chosen(self, row: int) -> None:
      """!Another shop was picked.
      @param row  its row
      @return None
      """
      if self._filling:
         return
      doc = self.battle_doc()
      names = inventory.shop_names(doc) if doc is not None else []
      if 0 <= row < len(names):
         self.selected = names[row]
         self._fill_items(inventory.shops(doc))

   def _edit(self, label: str, fn: Any) -> bool:
      """!One edit; a refused one refreshes the page back.
      @param label  undo label
      @param fn     callable
      @return True when it went through
      """
      ok = self.edit(label, fn)
      if not ok:
         self.host.changed()
      return ok

   def add_shop(self, name: str | None = None) -> bool:
      """!Adds a shop.
      @param name  its name, or None to ask
      @return True when added
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, "New shop", "Name:")
         if not ok:
            return False
      if self._edit("Add shop", lambda: inventory.add_shop(doc, name)):
         self.selected = name.strip()
         return True
      return False

   def rename_shop(self, new: str | None = None) -> bool:
      """!Renames the selected shop.
      @param new  the new name, or None to ask
      @return True when renamed
      """
      doc, old = self.battle_doc(), self.selected
      if doc is None or old is None:
         return False
      if new is None:
         new, ok = QtWidgets.QInputDialog.getText(self, "Rename shop", "New name:", text=old)
         if not ok:
            return False
      if self._edit("Rename shop", lambda: inventory.rename_shop(doc, old, new)):
         self.selected = new.strip()
         return True
      return False

   def remove_shop(self) -> bool:
      """!Removes the selected shop.
      @return True when removed
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      return self._edit("Remove shop", lambda: inventory.remove_shop(doc, name))

   def add_item(self, item: str) -> bool:
      """!Puts an item on the selected shop's list.
      @param item  item name
      @return True when added
      """
      doc, shop = self.battle_doc(), self.selected
      if doc is None or shop is None or not item:
         return False
      return self._edit("Shop item", lambda: inventory.add_shop_item(doc, shop, item))

   def remove_item(self) -> bool:
      """!Takes the selected item off the selected shop's list.
      @return True when removed
      """
      doc, shop = self.battle_doc(), self.selected
      row = self.item_list.currentRow()
      items = next((r[inventory.SHOP_ITEMS_KEY] for r in inventory.shops(doc) if r["name"] == shop), []) \
         if doc is not None else []
      if doc is None or shop is None or not 0 <= row < len(items):
         return False
      return self._edit("Shop item", lambda: inventory.remove_shop_item(doc, shop, items[row]))


class PassivesItemsPanel(BattlePanel):
   """!Passives and items, one tab each.

   @var errors
   Compile result line (each tab shows its own).
   @var _filling
   True while the panel fills its own widgets.
   """

   ## See EditorPanel.panel_id.
   panel_id = "passives_items"
   ## See EditorPanel.title.
   title = "Passives / Items"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the two tabs.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The passives.
      self.passives = PassivesTab(host)
      ## The items.
      self.items = ItemsTab(host)
      ## The shop lists.
      self.shops = ShopsTab(host)
      ## The tabs.
      self.tabs = QtWidgets.QTabWidget()
      self.tabs.addTab(self.passives, "Passives")
      self.tabs.addTab(self.items, "Items")
      self.tabs.addTab(self.shops, "Shops")
      lay = QtWidgets.QVBoxLayout(self)
      lay.addWidget(self.tabs)

   def tab(self, kind: str) -> HolderTab:
      """!A list's tab.
      @param kind  "passives" or "items"
      @return the tab
      """
      return self.passives if kind == "passives" else self.items

   def tab_title(self) -> str:
      """!"Passives / Items" in the game's words (e.g. "Abilities / Items").
      @return text
      """
      return f"{self.word('passive', True)} / {self.word('item', True)}"

   def refresh(self) -> None:
      """!Re-reads both tabs; their titles follow the game's words.
      @return None
      """
      self.tabs.setTabText(0, self.word("passive", True))
      self.tabs.setTabText(1, self.word("item", True))
      self.passives.refresh()
      self.items.refresh()
      self.shops.refresh()
