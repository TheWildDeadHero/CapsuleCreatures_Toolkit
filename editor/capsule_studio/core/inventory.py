"""!The bag side of items (D-26 section 2, engine G2): each item's bag and use
fields, its use logic, the shop lists, and test saves (the Bag page).

    "items": [{"name": "Tonic", "pocket": "supplies", "price": 30, "use": "both", "target": "member"}, ...]
    "shops": [{"name": "Corner Shop", "items": ["Tonic", "Mana Tea"]}]

Item fields (the engine's tools/battlec/inventory.py, re-exported by
battle_compiler, decides every value): pocket (a structure pocket, Structure
> Pockets; none: the item cannot go into the bag), price (0 to MAX_PRICE),
use (ITEM_USES: none | field | battle | both), target (ITEM_TARGETS: none |
member | move_slot | battler, battler for use "battle" only), key (never
consumed or sold), consumed and holdable (both default to not key). A use
needs its effect logic hook (USE_HOOKS: on use_field / on use_battle);
add_use_handler() writes a stub one into the item's `.ceffect` block.

A test save (capsule.testsave/1, the game folder's testsaves/NAME.json)
holds a bag by pocket: {"pockets": {POCKET: [{"item": NAME, "count": N}]}};
check() names what the manifests refuse (unknown items, an item in another
pocket, a count past the pocket's quantity_max, more items than its slots)
and export() writes the engine save image of that bag (the engine's
tools/save_layout.py image(): an empty party, the game's script banks zeroed,
for the game's first target platform unless one is named: C6), loadable by
a game's save::load(). G3: a test save may also box creatures ("boxes",
"current_box": core.structure.storage), written into the image's Boxes
section. F3: a test save may also hold the step effects' counters
("step_counters": core.structure.step_effects), written into the image's
Script section (their implicit variables). S5 (engine N3): a test save may
also hold the game's own block ("game": core.game_block), written into the
image's Game section.

Each manifest helper is one change: call it inside one edit(). An edit that
stops data that compiled from compiling is refused with the engine's
message. An item's rename follows the shops (core.battle.references()).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import battle, engine, logic
from .document import Document, DocumentError
from .structure import pockets as pocket_model
from .structure import storage as storage_model

if TYPE_CHECKING:
   from .battle import BattleProject

## A parsed JSON object.
JsonDict = dict[str, Any]

## The battle manifest's shop lists.
SHOPS_KEY = "shops"
## A shop's item list.
SHOP_ITEMS_KEY = "items"
## An item's fields this module edits (besides name, announce, handlers).
POCKET_KEY = "pocket"
## An item's price.
PRICE_KEY = "price"
## An item's use.
USE_KEY = "use"
## An item's target.
TARGET_KEY = "target"
## An item's key flag.
KEY_KEY = "key"
## An item's consumed flag.
CONSUMED_KEY = "consumed"
## An item's holdable flag.
HOLDABLE_KEY = "holdable"
## An item's egg flag (B2: it may be used on an egg; default refused).
EGGS_KEY = "allow_eggs"
## The flag fields.
FLAG_FIELDS = (KEY_KEY, CONSUMED_KEY, HOLDABLE_KEY, EGGS_KEY)
## The schema of a test save.
TESTSAVE_SCHEMA = "capsule.testsave/1"
## Where a game's test saves are (game folder / testsaves).
TESTSAVE_FOLDER = "testsaves"
## A test save's file suffix.
TESTSAVE_SUFFIX = ".json"
## A test save's bag: {pocket: [{"item", "count"}]}.
TESTSAVE_POCKETS = "pockets"
## A test save slot's item.
SLOT_ITEM = "item"
## A test save slot's count.
SLOT_COUNT = "count"
## Code of a new use handler: no effect until its logic is written.
NEW_USE_BODY = "fail;"


def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


# -- the engine's lists -----------------------------------------------------------------------------------------------

def item_fields() -> list[str]:
   """!The item fields the bag adds (the engine's ITEM_FIELDS).
   @return names
   """
   return list(_bc().ITEM_FIELDS)


def uses() -> list[str]:
   """!An item's uses (the engine's ITEM_USES).
   @return names, in capsule::inventory::Use order
   """
   return list(_bc().ITEM_USES)


def targets() -> list[str]:
   """!An item's targets (the engine's ITEM_TARGETS).
   @return names, in capsule::inventory::Target order
   """
   return list(_bc().ITEM_TARGETS)


def battle_targets() -> set[str]:
   """!The targets only a battle has (the engine's BATTLE_TARGETS).
   @return names
   """
   return set(_bc().BATTLE_TARGETS)


def use_hooks() -> dict[str, str]:
   """!The effect logic hook of each kind of use (the engine's USE_HOOKS: field -> use_field, battle ->
   use_battle).
   @return {use: hook}
   """
   return dict(_bc().USE_HOOKS)


def hooks_needed(use: str) -> list[str]:
   """!The hooks an item of a use needs.
   @param use  one of uses()
   @return hook names
   """
   bc = _bc()
   out = []
   if use in bc.FIELD_USES:
      out.append(bc.USE_HOOKS["field"])
   if use in bc.BATTLE_USES:
      out.append(bc.USE_HOOKS["battle"])
   return out


def max_price() -> int:
   """!The highest price (the engine's MAX_PRICE).
   @return the value
   """
   return int(_bc().MAX_PRICE)


# -- item fields ------------------------------------------------------------------------------------------------------

def fields_of(doc: Document, name: str) -> JsonDict:
   """!An item's bag and use fields with the defaults filled in (the engine's item_fields()).
   @param doc   any manifest Document of the battle
   @param name  the item
   @return {"pocket" (name or None), "price", "use", "target", "key", "consumed", "holdable", "allow_eggs"}; an
           item whose fields the engine refuses shows its raw values
   """
   e = battle.entry(battle.content_doc(doc), "items", name)
   names = pocket_model.pocket_names(doc)
   try:
      f = _bc().item_fields(e, [{"name": n} for n in names], name)
   except _bc().ManifestError:
      key = e.get(KEY_KEY) is True
      return {POCKET_KEY: e.get(POCKET_KEY), PRICE_KEY: e.get(PRICE_KEY, 0), USE_KEY: e.get(USE_KEY, "none"),
              TARGET_KEY: e.get(TARGET_KEY, "none"), KEY_KEY: key, CONSUMED_KEY: e.get(CONSUMED_KEY, not key),
              HOLDABLE_KEY: e.get(HOLDABLE_KEY, not key), EGGS_KEY: e.get(EGGS_KEY) is True}
   return {POCKET_KEY: f["pocket_name"], PRICE_KEY: f["price"], USE_KEY: f["use"], TARGET_KEY: f["target"],
           KEY_KEY: f["key"], CONSUMED_KEY: f["consumed"], HOLDABLE_KEY: f["holdable"], EGGS_KEY: f["allow_eggs"]}


def _guarded(doc: Document, change: Any) -> Any:
   """!Runs a change; refuses it with the engine's message when the battle data compiled before and does not after.
   @param doc     any manifest Document of the battle
   @param change  callable
   @return what it returned
   @throws DocumentError with the engine's message
   """
   project = logic.project_of(doc)
   before = project.error_now() if project is not None else None
   result = change()
   if before is None and project is not None:
      error = project.error_now()
      if error is not None:
         raise DocumentError(error)
   return result


def set_item_field(doc: Document, name: str, field: str, value: Any) -> None:
   """!Sets an item's bag or use field (a default value is left out of the manifest).
   @param doc    any manifest Document of the battle
   @param name   the item
   @param field  one of item_fields()
   @param value  the value: a pocket name or None, a price, a use, a target, a flag
   @return None
   @throws DocumentError for an unknown field or a value the engine refuses
   """
   if field not in item_fields():
      raise DocumentError(f"an item's bag field is one of {', '.join(item_fields())} (got {field!r})")
   e = battle.entry(battle.content_doc(doc), "items", name)
   if field == PRICE_KEY:
      try:
         value = int(value)
      except (TypeError, ValueError):
         raise DocumentError(f"price: a whole number 0-{max_price()} (got {value!r})") from None
   if field == POCKET_KEY and value is not None and value not in pocket_model.pocket_names(doc):
      raise DocumentError(f"pocket: one of {', '.join(pocket_model.pocket_names(doc)) or 'none'} (got {value!r})")
   if field == USE_KEY and value not in uses():
      raise DocumentError(f"use: one of {', '.join(uses())} (got {value!r})")
   if field == TARGET_KEY and value not in targets():
      raise DocumentError(f"target: one of {', '.join(targets())} (got {value!r})")
   if field in FLAG_FIELDS and not isinstance(value, bool):
      raise DocumentError(f"{field}: true or false (got {value!r})")

   project = logic.project_of(doc)

   def change() -> None:
      """!Writes the field and leaves defaults out; a use that needs a hook the logic lacks gets a stub handler.
      @return None
      """
      e[field] = value
      if field == USE_KEY and project is not None:
         have = use_logic(project, name)
         for hook in hooks_needed(value):
            if have[hook] is None:
               _add_handler(project, name, hook, f"Item {field}")
      key = e.get(KEY_KEY) is True
      defaults = {POCKET_KEY: None, PRICE_KEY: 0, USE_KEY: _bc().DEFAULT_USE, TARGET_KEY: _bc().DEFAULT_TARGET,
                  KEY_KEY: False, CONSUMED_KEY: not key, HOLDABLE_KEY: not key, EGGS_KEY: False}
      for k in item_fields():
         if k in e and e[k] == defaults[k]:
            del e[k]

   _guarded(doc, change)


def use_logic(project: BattleProject, name: str) -> dict[str, str | None]:
   """!An item's use handlers as text.
   @param project  BattleProject
   @param name     the item
   @return {hook: the handler's text, or None when the item's logic has none} for every use hook
   """
   out: dict[str, str | None] = {h: None for h in use_hooks().values()}
   ref = f"item{logic.OWNER_SEPARATOR}{name}"
   try:
      ast = logic.owner_ast(project, ref)
   except DocumentError:
      return out
   ec = engine.tool("effect_compiler")
   for h in ast.get("handlers", []):
      if h.get("on") in out:
         # the handler as its own block (the owner's other members left out), its body indented once
         one = {"owners": [{"owner": ast["owner"], "handlers": [h]}]}
         block = ec.format(one).strip("\n").split("\n")
         out[h["on"]] = "\n".join(line[len(ec.INDENT):] for line in block[1:-1])
   return out


def add_use_handler(project: BattleProject, name: str, hook: str, label: str = "Add use logic") -> None:
   """!Adds a stub use handler (`on HOOK { fail; }`: no effect until its logic is written) to an item's logic,
   making its `.ceffect` block when it has none.
   @param project  BattleProject
   @param name     the item
   @param hook     one of use_hooks()' hooks
   @param label    undo label
   @return None
   @throws DocumentError when the item has the handler already (its use grows to cover the hook)
   """
   if hook not in use_hooks().values():
      raise DocumentError(f"a use hook is one of {', '.join(use_hooks().values())} (got {hook!r})")
   if use_logic(project, name)[hook] is not None:
      raise DocumentError(f"item {name!r} has `on {hook}` already")
   e = battle.entry(project.battle, "items", name)
   use = fields_of(project.battle, name)[USE_KEY]
   if hook not in hooks_needed(use):
      # the item's use grows to the hook's (none -> field, battle -> both, ...): a handler of another use never runs
      grown = set(hooks_needed(use)) | {hook}
      e[USE_KEY] = next(u for u in uses() if set(hooks_needed(u)) == grown)
   _add_handler(project, name, hook, label)


def _add_handler(project: BattleProject, name: str, hook: str, label: str) -> None:
   """!Writes a stub use handler into an item's logic block (made when missing).
   @param project  BattleProject
   @param name     the item
   @param hook     the use hook
   @param label    undo label
   @return None
   """
   ref = f"item{logic.OWNER_SEPARATOR}{name}"
   if not any(r.kind == "item" and r.name == name for r in logic.owners(project, "item")):
      logic.add_owner(project, "item", name, label=label)
   ast = logic.owner_ast(project, ref)
   ast.setdefault("handlers", []).append({"on": hook, "body": [logic.parse_statement(NEW_USE_BODY)]})
   logic.set_owner_ast(project, ref, ast, label)


# -- shops ------------------------------------------------------------------------------------------------------------

def shops(doc: Document) -> list[JsonDict]:
   """!The shop lists.
   @param doc  any manifest Document of the battle
   @return [{"name", "items": [names]}] (copies)
   """
   given = battle.content_doc(doc).data.get(SHOPS_KEY)
   return [{"name": s.get("name"), SHOP_ITEMS_KEY: list(s.get(SHOP_ITEMS_KEY) or [])}
           for s in (given if isinstance(given, list) else []) if isinstance(s, dict)]


def shop_names(doc: Document) -> list[str]:
   """!The shop names in order (battle_ids.h SHOP_<NAME>; the script primitive `shop "NAME"`).
   @param doc  any manifest Document of the battle
   @return names
   """
   return [str(s["name"]) for s in shops(doc)]


def _live_shops(doc: Document) -> list[JsonDict]:
   """!The shop list for editing (created when absent).
   @param doc  any manifest Document of the battle
   @return the live list
   """
   data = battle.content_doc(doc).data
   if not isinstance(data.get(SHOPS_KEY), list):
      data[SHOPS_KEY] = []
   return data[SHOPS_KEY]


def _shop(doc: Document, name: str) -> JsonDict:
   """!A shop by name.
   @param doc   any manifest Document of the battle
   @param name  shop name
   @return its live dict
   @throws DocumentError when there is none
   """
   for s in _live_shops(doc):
      if isinstance(s, dict) and s.get("name") == name:
         return s
   raise DocumentError(f"no shop {name!r} (shops: {', '.join(shop_names(doc)) or 'none'})")


def add_shop(doc: Document, name: str) -> None:
   """!Adds an empty shop.
   @param doc   any manifest Document of the battle
   @param name  its name
   @return None
   """
   if not isinstance(name, str) or not name.strip():
      raise DocumentError("a shop needs a name")
   if name.strip() in shop_names(doc):
      raise DocumentError(f"there is already a shop {name.strip()!r}")
   _guarded(doc, lambda: _live_shops(doc).append({"name": name.strip(), SHOP_ITEMS_KEY: []}))


def remove_shop(doc: Document, name: str) -> None:
   """!Removes a shop (scripts naming it stop compiling: the script page says so).
   @param doc   any manifest Document of the battle
   @param name  shop name
   @return None
   """
   s = _shop(doc, name)
   _guarded(doc, lambda: _live_shops(doc).remove(s))


def rename_shop(doc: Document, old: str, new: str) -> None:
   """!Renames a shop.
   @param doc  any manifest Document of the battle
   @param old  current name
   @param new  new name
   @return None
   """
   s = _shop(doc, old)
   if not isinstance(new, str) or not new.strip():
      raise DocumentError("a shop needs a name")
   if new.strip() != old and new.strip() in shop_names(doc):
      raise DocumentError(f"there is already a shop {new.strip()!r}")
   _guarded(doc, lambda: s.update({"name": new.strip()}))


def add_shop_item(doc: Document, shop: str, item: str, index: int | None = None) -> None:
   """!Puts an item on a shop's list (it needs a price and a pocket: the engine refuses one without).
   @param doc    any manifest Document of the battle
   @param shop   shop name
   @param item   item name
   @param index  position, or None for the end
   @return None
   """
   s = _shop(doc, shop)
   battle.entry(battle.content_doc(doc), "items", item)
   lst = s.setdefault(SHOP_ITEMS_KEY, [])
   at = len(lst) if index is None else max(0, min(len(lst), int(index)))
   _guarded(doc, lambda: lst.insert(at, item))


def remove_shop_item(doc: Document, shop: str, item: str) -> None:
   """!Takes an item off a shop's list.
   @param doc   any manifest Document of the battle
   @param shop  shop name
   @param item  item name
   @return None
   """
   lst = _shop(doc, shop).setdefault(SHOP_ITEMS_KEY, [])
   if item not in lst:
      raise DocumentError(f"shop {shop!r} does not sell {item!r}")
   _guarded(doc, lambda: lst.remove(item))


# -- test saves -------------------------------------------------------------------------------------------------------

def testsave_folder(project: BattleProject) -> Path:
   """!Where the game's test saves are (game folder / testsaves).
   @param project  BattleProject
   @return folder (may not exist yet)
   """
   from . import bench   # local: core.bench imports core.battle
   return bench.game_folder(project) / TESTSAVE_FOLDER


def testsave_paths(project: BattleProject) -> list[Path]:
   """!The game's test saves.
   @param project  BattleProject
   @return files, sorted
   """
   folder = testsave_folder(project)
   return sorted(folder.glob(f"*{TESTSAVE_SUFFIX}")) if folder.is_dir() else []


def new_testsave(project: BattleProject, name: str) -> Document:
   """!Writes an empty test save (testsaves/NAME.json).
   @param project  BattleProject
   @param name     file name stem
   @return the saved Document
   @throws DocumentError when the name is taken or not a plain file name
   """
   stem = name.strip().removesuffix(TESTSAVE_SUFFIX)
   if not stem or Path(stem).name != stem or stem.startswith("."):
      raise DocumentError(f"{name!r}: a test save's name is a plain file name (no folders)")
   path = testsave_folder(project) / (stem + TESTSAVE_SUFFIX)
   if path.exists():
      raise DocumentError(f"{path.name} already exists")
   doc = Document({"schema": TESTSAVE_SCHEMA, TESTSAVE_POCKETS: {}}, path, TESTSAVE_SCHEMA)
   doc.save()
   return doc


def open_testsave(project: BattleProject, name: str | Path) -> Document:
   """!Opens a test save by name (in testsaves/) or path.
   @param project  BattleProject
   @param name     stem, file name or path
   @return Document
   """
   path = Path(name)
   if not path.is_absolute() and len(path.parts) == 1:
      path = testsave_folder(project) / (path.name if path.suffix else path.name + TESTSAVE_SUFFIX)
   return Document.open(path, TESTSAVE_SCHEMA)


def bag_of(save: Document) -> dict[str, list[JsonDict]]:
   """!A test save's bag by pocket.
   @param save  test save Document
   @return {pocket: [{"item", "count"}]} (copies)
   """
   given = save.data.get(TESTSAVE_POCKETS)
   return {str(k): [dict(s) for s in v if isinstance(s, dict)] for k, v in
           (given.items() if isinstance(given, dict) else []) if isinstance(v, list)}


def _pocket_of(doc: Document, item: str) -> str | None:
   """!An item's pocket.
   @param doc   any manifest Document of the battle
   @param item  item name
   @return pocket name, or None
   """
   return fields_of(doc, item)[POCKET_KEY]


def put(save: Document, doc: Document, item: str, count: int) -> int:
   """!Adds items to a test save (into the item's own pocket; inside save.edit()).
   @param save   test save Document
   @param doc    any manifest Document of the battle
   @param item   item name
   @param count  how many (1 or more)
   @return the item's count after it
   @throws DocumentError for an item without a pocket, or past its pocket's quantity_max or slots
   """
   pocket = _pocket_of(doc, item)
   if pocket is None:
      raise DocumentError(f"{item!r} has no pocket (it cannot go into the bag)")
   if not isinstance(count, int) or count < 1:
      raise DocumentError(f"a count is 1 or more (got {count!r})")
   row = next(r for r in pocket_model.rows(doc) if r["name"] == pocket)
   bag = save.data.setdefault(TESTSAVE_POCKETS, {})
   slots = bag.setdefault(pocket, [])
   slot = next((s for s in slots if s.get(SLOT_ITEM) == item), None)
   have = slot[SLOT_COUNT] if slot is not None else 0
   if have + count > row["quantity_max"]:
      raise DocumentError(f"{pocket} holds at most {row['quantity_max']} of one item")
   if slot is None:
      if len(slots) >= row["capacity"]:
         raise DocumentError(f"{pocket} is full ({row['capacity']} slots)")
      slots.append({SLOT_ITEM: item, SLOT_COUNT: count})
   else:
      slot[SLOT_COUNT] = have + count
   return have + count


def take(save: Document, doc: Document, item: str, count: int | None = None) -> int:
   """!Takes items out of a test save (every one without a count; inside save.edit()).
   @param save   test save Document
   @param doc    any manifest Document of the battle
   @param item   item name
   @param count  how many, or None for all
   @return what is left
   """
   for pocket, slots in save.data.get(TESTSAVE_POCKETS, {}).items():
      for s in list(slots):
         if s.get(SLOT_ITEM) == item:
            left = 0 if count is None else s[SLOT_COUNT] - count
            if left < 0:
               raise DocumentError(f"the save holds {s[SLOT_COUNT]} {item}")
            if left == 0:
               slots.remove(s)
            else:
               s[SLOT_COUNT] = left
            return left
   raise DocumentError(f"the save holds no {item!r}")


def check(save: Document, doc: Document) -> list[str]:
   """!What the manifests refuse in a test save.
   @param save  test save Document
   @param doc   any manifest Document of the battle
   @return problems ([] when it exports)
   """
   out = []
   names = [i.get("name") for i in battle.entries(battle.content_doc(doc), "items") if isinstance(i, dict)]
   rows = {r["name"]: r for r in pocket_model.rows(doc)}
   for pocket, slots in bag_of(save).items():
      if pocket not in rows:
         out.append(f"no pocket {pocket!r}")
         continue
      if len(slots) > rows[pocket]["capacity"]:
         out.append(f"{pocket}: {len(slots)} items, {rows[pocket]['capacity']} slots")
      for s in slots:
         item, count = s.get(SLOT_ITEM), s.get(SLOT_COUNT)
         if item not in names:
            out.append(f"{pocket}: unknown item {item!r}")
         elif _pocket_of(doc, item) != pocket:
            out.append(f"{pocket}: {item} belongs in {_pocket_of(doc, item) or 'no pocket'}")
         if not isinstance(count, int) or not 1 <= count <= rows[pocket]["quantity_max"]:
            out.append(f"{pocket}: {item} x{count} (1-{rows[pocket]['quantity_max']})")
   from . import game_block
   from .structure import nursery, step_effects   # local: core.structure.step_effects reads the game's files
   return out + storage_model.check_boxes(save, doc) + step_effects.check_counters(save, doc) + \
      nursery.check_test(save, doc) + game_block.check_game(save)


def export_platform(project: BattleProject) -> str | None:
   """!The platform a test save is exported for when none is named (C6): the game's first target (its
   reference/project.json "targets"), else the engine's default (the GBA).
   @param project  BattleProject
   @return a platform name, or None (the engine's default)
   """
   from .structure import stats   # local: core.structure.stats imports core modules that import this one
   try:
      targets = stats.project_targets(project.battle.path)
   except DocumentError:
      return None
   return targets[0] if targets else None


def script_banks(project: BattleProject) -> list[JsonDict]:
   """!The game's script sub-banks (the engine's save_layout.script_banks(): their shape hashes), so an exported
   image carries the game's Script section (C6, review4 finding 3).
   @param project  BattleProject
   @return the sub-banks ([] without a scripts manifest)
   @throws DocumentError when the scripts do not compile
   """
   manifest = project.scripts_manifest()
   if manifest is None:
      return []
   sl = engine.tool("save_layout")
   try:
      return list(sl.script_banks(manifest))
   except (sl.bc.ManifestError, OSError) as e:
      raise DocumentError(f"the game's scripts do not compile: {e}") from None


def image_of(save: Document, project: BattleProject, platform: str | None = None) -> bytes:
   """!The engine save image of a test save's bag and boxes (the engine's save_layout.image(): an empty party,
   the game's script banks zeroed with their shape hashes (C6), sequence 1; G3: the boxed creatures as records in
   the Boxes section).
   @param save      test save Document
   @param project   BattleProject
   @param platform  target platform (None: the game's first target, else the GBA's)
   @return one copy's bytes
   @throws DocumentError when the save or the battle data do not check
   """
   problems = check(save, project.battle)
   if problems:
      raise DocumentError("the test save does not check: " + "; ".join(problems))
   platform = platform or export_platform(project)
   compiled, error = project.compile(platform)
   if compiled is None:
      raise DocumentError(f"the battle data does not compile: {error}")
   names = compiled["names"]["items"]
   order = [p["name"] for p in compiled["inventory"]["pockets"]]
   bag = {order.index(pocket): [(names.index(s[SLOT_ITEM]) + 1, s[SLOT_COUNT]) for s in slots]
          for pocket, slots in bag_of(save).items()}
   boxes = storage_model.records_of(save, compiled)
   from .structure import nursery, step_effects   # local: core.structure.step_effects reads the game's files
   banks = script_banks(project)
   values = step_effects.counter_values(save)
   if values and not banks:
      raise DocumentError("the test save's step counters need the game's scripts (their implicit variables)")
   held, result = nursery.image_parts(save, compiled)   # B2: the nursery's records and its waiting result
   image = bytes(engine.tool("save_layout").image(compiled, bag, banks=banks, boxes=boxes,
                                                  current_box=storage_model.current_box(save), values=values,
                                                  nursery=held, nursery_result=result))
   from . import game_block
   return game_block.with_game(image, save)   # S5 (N3): the game's own block in the Game section


def export(save: Document, project: BattleProject, out: str | Path, platform: str | None = None) -> int:
   """!Writes a test save's engine image to a file (a desktop game reads it as its save file).
   @param save      test save Document
   @param project   BattleProject
   @param out       the file
   @param platform  target platform (None: the game's first target, else the GBA's)
   @return bytes written
   """
   data = image_of(save, project, platform)
   Path(out).write_bytes(data)
   return len(data)


def lines(save: Document, doc: Document) -> list[str]:
   """!A test save as text (CLI `testsave show`).
   @param save  test save Document
   @param doc   any manifest Document of the battle
   @return lines
   """
   out = []
   for pocket, slots in bag_of(save).items():
      out.append(f"{pocket}: " + (", ".join(f"{s.get(SLOT_ITEM)} x{s.get(SLOT_COUNT)}" for s in slots) or "empty"))
   problems = check(save, doc)
   from . import game_block
   from .structure import nursery, step_effects   # local: core.structure.step_effects reads the game's files
   return (out or ["(an empty bag)"]) + storage_model.boxed_lines(save, doc) + step_effects.counter_lines(save, doc) \
      + nursery.test_lines(save) + game_block.lines(save) + [f"problem: {p}" for p in problems]


def dumps(save: Document) -> str:
   """!A test save's JSON (the CLI's --json).
   @param save  test save Document
   @return text
   """
   return json.dumps(copy.deepcopy(save.data), indent=1)
