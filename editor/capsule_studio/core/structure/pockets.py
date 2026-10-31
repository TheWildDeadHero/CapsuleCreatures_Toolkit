"""!The bag's pockets (D-26 section 2, engine G2): the structure manifest's
"pockets" list.

    "pockets": [{"name": "supplies", "label": "Supplies", "capacity": 20, "quantity_max": 99, "sort": "added"},
                {"name": "key", "label": "Key", "capacity": 16, "quantity_max": 1}]

Each pocket is a slice of the bag's slots: "capacity" distinct items of up
to "quantity_max" each, ordered by "sort" (added: as they come in; index: by
item id; name: by display name). An item names its pocket ("pocket", Content
> Items); an item with none cannot go into the bag. A structure without the
list has no bag.

The engine's tools/battlec/inventory.py is the one authority (re-exported by
battle_compiler): compile_pockets() checks the list (names, quantities, sort
rules, the platform's most pockets and slots: build_settings PLATFORM_LIMITS
max_pockets / max_bag_slots); the battle compiler checks the items' pockets
and the shops against it.

Each editing helper is one change: call it inside one edit() of either
manifest and Undo takes the whole change back. A rename follows the items
naming the pocket; a pocket that items name cannot go (move them first:
move_items()). An edit that stops data that compiled from compiling is
refused with the engine's message. Saved games keep their bag slots by
position: a change of the pockets' slices makes an older save image of
another shape (capsule/save/save.h refuses it).
"""
from __future__ import annotations

import copy
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypedDict

from .. import battle, engine, logic
from ..document import Document, DocumentError
from . import stats

if TYPE_CHECKING:
   from ..battle import BattleProject

## A parsed JSON object.
JsonDict = dict[str, Any]

## The structure manifest's list of pockets.
POCKETS_KEY = "pockets"
## A pocket's name key.
NAME_KEY = "name"
## A pocket's display label (default its name).
LABEL_KEY = "label"
## A pocket's slot count.
CAPACITY_KEY = "capacity"
## A pocket's most of one item.
QUANTITY_KEY = "quantity_max"
## A pocket's sort rule.
SORT_KEY = "sort"
## An item's pocket.
ITEM_POCKET_KEY = "pocket"
## The fields set_field() sets.
FIELDS = (LABEL_KEY, CAPACITY_KEY, QUANTITY_KEY, SORT_KEY)
## The platform limits (build_settings.PLATFORM_LIMITS).
POCKET_LIMIT_KEY = "max_pockets"
## The platform limit of the slots of every pocket together.
SLOT_LIMIT_KEY = "max_bag_slots"
## Capacity of a new pocket.
NEW_CAPACITY = 20
## Location the compiler's messages name.
WHERE = "structure"


class PocketRow(TypedDict):
   """!One pocket as the page and the CLI show it."""
   ## Pocket index (battle_ids.h POCKET_<NAME>).
   index: int
   ## Name.
   name: str
   ## Display label.
   label: str
   ## Slots.
   capacity: int
   ## Most of one item a slot holds.
   quantity_max: int
   ## Sort rule.
   sort: str
   ## Its first slot in the bag.
   first: int
   ## Items naming it.
   items: int


def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


def sort_rules() -> list[str]:
   """!The sort rules a pocket may have (the engine's SORT_RULES).
   @return names, in capsule::inventory::SortRule order
   """
   return list(_bc().SORT_RULES)


def default_sort() -> str:
   """!A pocket's sort rule when it states none.
   @return the engine's DEFAULT_SORT
   """
   return str(_bc().DEFAULT_SORT)


def default_quantity() -> int:
   """!A pocket's quantity_max when it states none.
   @return the engine's DEFAULT_QUANTITY_MAX
   """
   return int(_bc().DEFAULT_QUANTITY_MAX)


def max_quantity() -> int:
   """!The most of one item a slot holds on any engine.
   @return the engine's MAX_QUANTITY
   """
   return int(_bc().MAX_QUANTITY)


def _limit(key: str, targets: list[str] | None) -> int:
   """!The smallest limit of the targets.
   @param key      PLATFORM_LIMITS key
   @param targets  platforms, or None for the default targets
   @return the limit
   @throws DocumentError for an unknown platform
   """
   bs = engine.tool("build_settings")
   try:
      return min(bs.platform_limits(t)[key] for t in (targets or stats.DEFAULT_TARGETS))
   except bs.SettingsError as e:
      raise DocumentError(str(e)) from None


def max_pockets(targets: list[str] | None = None) -> int:
   """!Most pockets every target's engine holds (capsule::inventory::kMaxPockets).
   @param targets  platforms, or None for the default targets
   @return the smallest limit
   """
   return _limit(POCKET_LIMIT_KEY, targets)


def max_slots(targets: list[str] | None = None) -> int:
   """!Most bag slots every target's engine holds (capsule::inventory::kMaxBagSlots).
   @param targets  platforms, or None for the default targets
   @return the smallest limit
   """
   return _limit(SLOT_LIMIT_KEY, targets)


def is_stated(doc: Document) -> bool:
   """!Whether the structure states pockets (else the game has no bag).
   @param doc  any manifest Document of the battle
   @return True when "pockets" is given
   """
   return POCKETS_KEY in battle.data_of(doc, POCKETS_KEY)


def pockets(doc: Document) -> list[JsonDict]:
   """!The pockets in order, defaults filled in.
   @param doc  any manifest Document of the battle
   @return [{"name", "label", "capacity", "quantity_max", "sort"}] (entries that are not objects with a name are
           left out)
   """
   given = battle.data_of(doc, POCKETS_KEY).get(POCKETS_KEY)
   out = []
   for e in given if isinstance(given, list) else []:
      if isinstance(e, dict) and isinstance(e.get(NAME_KEY), str):
         out.append({NAME_KEY: e[NAME_KEY], LABEL_KEY: e.get(LABEL_KEY, e[NAME_KEY]),
                     CAPACITY_KEY: e.get(CAPACITY_KEY, 0), QUANTITY_KEY: e.get(QUANTITY_KEY, default_quantity()),
                     SORT_KEY: e.get(SORT_KEY, default_sort())})
   return out


def pocket_names(doc: Document | None) -> list[str]:
   """!The pocket names in order (the choice list of an item's pocket).
   @param doc  any manifest Document of the battle, or None
   @return names
   """
   return [p[NAME_KEY] for p in pockets(doc)] if doc is not None else []


def _items(doc: Document) -> list[JsonDict]:
   """!The battle's items (the content manifest's).
   @param doc  any manifest Document of the battle
   @return item dicts
   """
   return [i for i in battle.entries(doc, "items") if isinstance(i, dict)]


def users(doc: Document, name: str) -> list[str]:
   """!The items naming a pocket.
   @param doc   any manifest Document of the battle
   @param name  pocket name
   @return item names
   """
   _index(doc, name)
   return [str(i.get("name")) for i in _items(doc) if i.get(ITEM_POCKET_KEY) == name]


def rows(doc: Document) -> list[PocketRow]:
   """!The pockets with their slices and the items naming them.
   @param doc  any manifest Document of the battle
   @return one row per pocket
   """
   out: list[PocketRow] = []
   first = 0
   items = _items(doc)
   for i, p in enumerate(pockets(doc)):
      capacity = p[CAPACITY_KEY] if isinstance(p[CAPACITY_KEY], int) else 0
      out.append(PocketRow(index=i, name=p[NAME_KEY], label=str(p[LABEL_KEY]), capacity=capacity,
                           quantity_max=p[QUANTITY_KEY], sort=str(p[SORT_KEY]), first=first,
                           items=sum(1 for it in items if it.get(ITEM_POCKET_KEY) == p[NAME_KEY])))
      first += capacity
   return out


def slot_count(doc: Document) -> int:
   """!The bag's slots (every pocket's capacity together).
   @param doc  any manifest Document of the battle
   @return slots
   """
   return sum(r["capacity"] for r in rows(doc))


def _index(doc: Document, name: str) -> int:
   """!A pocket's index.
   @param doc   any manifest Document of the battle
   @param name  pocket name
   @return the index
   @throws DocumentError when there is no such pocket
   """
   names = pocket_names(doc)
   if name not in names:
      raise DocumentError(f"no pocket {name!r} (pockets: {', '.join(names) or 'none'})")
   return names.index(name)


# -- the engine's compile ---------------------------------------------------------------------------------------------

def compile_check(doc: Document, targets: list[str] | None = None) -> tuple[list[JsonDict] | None, str | None]:
   """!Compiles the pockets with the engine's compile_pockets() (the smallest limits of the targets).
   @param doc      any manifest Document of the battle
   @param targets  platforms whose caps apply, or None for the default targets
   @return (compiled pockets or None, the compiler's message or None)
   """
   bc = _bc()
   try:
      limits = {POCKET_LIMIT_KEY: max_pockets(targets), SLOT_LIMIT_KEY: max_slots(targets)}
      given = bc.strip(copy.deepcopy(battle.data_of(doc, POCKETS_KEY).get(POCKETS_KEY)))
      enc = bc.Texts(engine.tool("text_encoder").DEFAULT)
      return bc.compile_pockets(given, limits, WHERE, enc), None
   except Exception as e:   # ManifestError, DocumentError, type errors in odd data
      return None, str(e)


def _guarded(doc: Document, change: Callable[[], Any]) -> Any:
   """!Runs a change; refuses it with the engine's message when the pockets (or the whole battle data) compiled
   before and do not after (raised inside the edit, which puts the manifests back).
   @param doc     any manifest Document of the battle
   @param change  the change
   @return what change() returned
   @throws DocumentError with the engine's message
   """
   targets = stats.project_targets(doc.path)
   project: BattleProject | None = logic.project_of(doc)
   _p, before = compile_check(doc, targets)
   whole_before = project.error_now() if project is not None else None
   result = change()
   _p, error = compile_check(doc, targets)
   if before is None and error is not None:
      raise DocumentError(error)
   if whole_before is None and project is not None:
      error = project.error_now()
      if error is not None:
         raise DocumentError(error)
   return result


def _live(doc: Document) -> list[JsonDict]:
   """!The pocket list for editing (created when the structure states none).
   @param doc  any manifest Document of the battle
   @return the live list
   """
   data = battle.data_of(doc, POCKETS_KEY)
   if not isinstance(data.get(POCKETS_KEY), list):
      data[POCKETS_KEY] = []
   return data[POCKETS_KEY]


def _check_name(doc: Document, name: Any, current: str | None = None) -> str:
   """!A pocket name: a lower-case identifier (the engine's POCKET_NAME) no other pocket has.
   @param doc      any manifest Document of the battle
   @param name     the wanted name
   @param current  the name being renamed, or None
   @return the name (stripped)
   @throws DocumentError when it is not one
   """
   if not isinstance(name, str) or not _bc().POCKET_NAME.match(name.strip()):
      raise DocumentError(f"a pocket's name is a lower-case identifier (got {name!r})")
   name = name.strip()
   if name != current and name in pocket_names(doc):
      raise DocumentError(f"there is already a pocket {name!r}")
   return name


# -- editing (inside one edit()) -------------------------------------------------------------------------------------

def add_pocket(doc: Document, name: str, label: str | None = None, capacity: int = NEW_CAPACITY,
               index: int | None = None) -> int:
   """!Adds a pocket.
   @param doc       any manifest Document of the battle
   @param name      its name
   @param label     its label, or None (the name)
   @param capacity  its slots
   @param index     position, or None for the end
   @return its index
   @throws DocumentError for a taken or invalid name, a full list, or data the engine then refuses
   """
   name = _check_name(doc, name)
   most = max_pockets(stats.project_targets(doc.path))
   count = len(pocket_names(doc))
   if count >= most:
      raise DocumentError(f"at most {most} pockets (the engine's limit on every target)")
   at = count if index is None else max(0, min(count, int(index)))

   def change() -> int:
      """!Inserts the pocket.
      @return its index
      """
      entry: JsonDict = {NAME_KEY: name}
      if label is not None and label != name:
         entry[LABEL_KEY] = label
      entry[CAPACITY_KEY] = capacity
      _live(doc).insert(at, entry)
      return at

   return _guarded(doc, change)


def remove_pocket(doc: Document, name: str) -> None:
   """!Removes a pocket no item names.
   @param doc   any manifest Document of the battle
   @param name  pocket name
   @return None
   @throws DocumentError while items name it (move_items() first)
   """
   i = _index(doc, name)
   named = users(doc, name)
   if named:
      raise DocumentError(f"pocket {name!r} holds {', '.join(named)}: move them to another pocket first")
   _guarded(doc, lambda: _live(doc).pop(i))


def rename_pocket(doc: Document, old: str, new: str) -> int:
   """!Renames a pocket; the items naming it follow.
   @param doc  any manifest Document of the battle
   @param old  current name
   @param new  new name
   @return items updated
   """
   i = _index(doc, old)
   new = _check_name(doc, new, old)
   if new == old:
      return 0

   def change() -> int:
      """!Renames the pocket and its items' pocket.
      @return items updated
      """
      n = 0
      for it in _items(doc):
         if it.get(ITEM_POCKET_KEY) == old:
            it[ITEM_POCKET_KEY] = new
            n += 1
      # a pocket without its own label shows its name: the label follows
      _live(doc)[i][NAME_KEY] = new
      return n

   return _guarded(doc, change)


def move_pocket(doc: Document, name: str, delta: int) -> bool:
   """!Moves a pocket up or down (its slice of the bag moves with it).
   @param doc    any manifest Document of the battle
   @param name   pocket name
   @param delta  -1 up, +1 down
   @return True if it moved
   """
   i = _index(doc, name)
   j = i + delta
   if not 0 <= j < len(pocket_names(doc)):
      return False

   def change() -> None:
      """!Swaps the two pockets.
      @return None
      """
      lst = _live(doc)
      lst[i], lst[j] = lst[j], lst[i]

   _guarded(doc, change)
   return True


def set_field(doc: Document, name: str, field: str, value: Any) -> None:
   """!Sets a pocket's label, capacity, quantity_max or sort (the default value is left out).
   @param doc    any manifest Document of the battle
   @param name   pocket name
   @param field  one of FIELDS
   @param value  the value (numbers as int or digits)
   @return None
   @throws DocumentError for an unknown field or a value the engine refuses
   """
   i = _index(doc, name)
   if field not in FIELDS:
      raise DocumentError(f"a pocket's field is one of {', '.join(FIELDS)} (got {field!r})")
   if field in (CAPACITY_KEY, QUANTITY_KEY):
      try:
         value = int(value)
      except (TypeError, ValueError):
         raise DocumentError(f"{field}: a whole number (got {value!r})") from None
   if field == SORT_KEY and value not in sort_rules():
      raise DocumentError(f"sort: one of {', '.join(sort_rules())} (got {value!r})")

   def change() -> None:
      """!Writes the field.
      @return None
      """
      entry = _live(doc)[i]
      default = {LABEL_KEY: entry[NAME_KEY], QUANTITY_KEY: default_quantity(), SORT_KEY: default_sort()}.get(field)
      if field != CAPACITY_KEY and value == default:
         entry.pop(field, None)
      else:
         entry[field] = value

   _guarded(doc, change)


def move_items(doc: Document, old: str, new: str | None) -> int:
   """!Moves every item of a pocket into another one (or out of the bag: None).
   @param doc  any manifest Document of the battle
   @param old  pocket name
   @param new  the pocket they go to, or None (no pocket)
   @return items moved
   """
   _index(doc, old)
   if new is not None:
      _index(doc, new)

   def change() -> int:
      """!Rewrites the items' pocket.
      @return items moved
      """
      n = 0
      for it in _items(doc):
         if it.get(ITEM_POCKET_KEY) == old:
            if new is None:
               it.pop(ITEM_POCKET_KEY)
            else:
               it[ITEM_POCKET_KEY] = new
            n += 1
      return n

   return _guarded(doc, change)


# -- report -----------------------------------------------------------------------------------------------------------

def budget(doc: Document, targets: list[str] | None = None) -> tuple[str, bool]:
   """!The pockets and slots against the engine's limits.
   @param doc      any manifest Document of the battle
   @param targets  platforms, or None for the default targets
   @return (e.g. "4/8 pockets, 60/256 slots (gba)", over a limit)
   """
   chosen = targets or stats.DEFAULT_TARGETS
   count, slots = len(pocket_names(doc)), slot_count(doc)
   most, room = max_pockets(chosen), max_slots(chosen)
   text = f"{count}/{most} pockets, {slots}/{room} bag slots ({', '.join(chosen)})"
   return text, count > most or slots > room


def lines(doc: Document, targets: list[str] | None = None) -> list[str]:
   """!The pockets as text (CLI `pocket list`), then the budget.
   @param doc      any manifest Document of the battle
   @param targets  platforms, or None for the default targets
   @return lines
   """
   out = [f"{r['index']} {r['name']} ({r['label']}): {r['capacity']} slots from {r['first']}, up to "
          f"{r['quantity_max']} each, sort {r['sort']}, {r['items']} item(s)" for r in rows(doc)]
   if not is_stated(doc):
      out.append("(no pockets: the structure states no bag)")
   return out + [budget(doc, targets)[0]]
