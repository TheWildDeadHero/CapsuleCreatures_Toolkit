"""!The passive slots of battle data (D-25 decision 6, engine C1): the
structure manifest's "passive_slots" list.

    "passive_slots": [{"name": "first"}, {"name": "second"},
                      {"name": "hidden", "rolled": false}]

Each species names up to one passive per slot (its "passives" list, by
position); a party member names the slot its creature has ("passive": the
slot's index or name; default the first); the generation entry
{"role": "passive_selector", "random_range": [0, "last"]} rolls one of the
rolled slots ("rolled": false is a slot only data or logic gives, such as a
Classic-style hidden one). A structure without the list has the engine's
DEFAULT_PASSIVE_SLOTS (one rolled slot); the first edit writes the list.

The engine's battlec/content.py is the one authority: compile_passive_slots()
checks the list (names, the platform's most slots: build_settings
PLATFORM_LIMITS max_passive_slots), the battle compiler checks the species'
passives and the members' slots against it and the record layout's
passive_selector role against the slot count (check_layout_fits()).

Each editing helper is one change: call it inside one edit() of either
manifest (the partner opens the other's step) and Undo takes the whole change
back. A rename follows the members naming the slot by name; a removal drops
the slot's place from every species' passives and the members (and the
saved bench scenarios' members) naming it fall back to the first slot; a
move swaps the species' passives and the members' and bench scenarios'
slot numbers. An edit that stops data that compiled from compiling is
refused with the engine's message. Creature records already saved keep the
slot number their passive_selector holds, so a removal or move changes their
passive: saved_records_warning() says how (the editors ask, the CLI wants
--force; C4).
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

## The structure manifest's list of passive slots.
SLOTS_KEY = "passive_slots"
## A slot's name key.
NAME_KEY = "name"
## A slot's "the generation list may roll it" key.
ROLLED_KEY = "rolled"
## A species' passives, one per slot (by position).
SPECIES_KEY = "passives"
## A party member's slot (an index or a slot name).
MEMBER_KEY = "passive"
## The record role holding a creature's slot (the generation list rolls it).
SELECTOR_ROLE = "passive_selector"
## The platform limit (build_settings.PLATFORM_LIMITS).
LIMIT_KEY = "max_passive_slots"
## Location the compiler's messages name.
WHERE = "structure"


class SlotRow(TypedDict):
   """!One passive slot as the page and the CLI show it."""
   ## Slot index (the members' and the selector's number).
   index: int
   ## Slot name.
   name: str
   ## The generation list may roll it.
   rolled: bool
   ## Species naming a passive in it.
   species: int
   ## Party members naming it (by index or name; a member naming none has the first).
   members: int


def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


def default_slots() -> list[JsonDict]:
   """!The slots of a structure that states none (the engine's DEFAULT_PASSIVE_SLOTS).
   @return a copy
   """
   return copy.deepcopy(list(_bc().DEFAULT_PASSIVE_SLOTS))


def default_rolled() -> bool:
   """!A slot's "rolled" when it states none (the engine's DEFAULT_ROLLED).
   @return the value
   """
   return bool(_bc().DEFAULT_ROLLED)


def max_slots(targets: list[str] | None = None) -> int:
   """!Most passive slots every target's engine holds (capsule::battle::kMaxPassiveSlots).
   @param targets  platforms, or None for the default targets
   @return the smallest limit
   @throws DocumentError for an unknown platform
   """
   bs = engine.tool("build_settings")
   try:
      return min(bs.platform_limits(t)[LIMIT_KEY] for t in (targets or stats.DEFAULT_TARGETS))
   except bs.SettingsError as e:
      raise DocumentError(str(e)) from None


def is_stated(doc: Document) -> bool:
   """!Whether the structure states its passive slots (else the engine's default applies).
   @param doc  any manifest Document of the battle
   @return True when "passive_slots" is given
   """
   return SLOTS_KEY in battle.data_of(doc, SLOTS_KEY)


def slots(doc: Document) -> list[JsonDict]:
   """!The passive slots in slot order, "rolled" filled in (the default list when none is stated).
   @param doc  any manifest Document of the battle
   @return [{"name", "rolled"}] (entries that are not objects with a name are left out)
   """
   given = battle.data_of(doc, SLOTS_KEY).get(SLOTS_KEY)
   entries = given if isinstance(given, list) else default_slots()
   return [{NAME_KEY: e[NAME_KEY], ROLLED_KEY: e.get(ROLLED_KEY, default_rolled())} for e in entries
           if isinstance(e, dict) and isinstance(e.get(NAME_KEY), str)]


def slot_names(doc: Document | None) -> list[str]:
   """!The slot names in slot order.
   @param doc  any manifest Document of the battle, or None (the engine's default slots)
   @return names
   """
   if doc is None:
      return [e[NAME_KEY] for e in default_slots()]
   return [e[NAME_KEY] for e in slots(doc)]


def slot_count(doc: Document | None) -> int:
   """!How many passive slots a species has.
   @param doc  any manifest Document of the battle, or None (the engine's default)
   @return count
   """
   return len(slot_names(doc))


def selector_max(doc: Document) -> int | None:
   """!The highest slot index the record layout's passive_selector role holds.
   @param doc  any manifest Document of the battle
   @return 2^width - 1, or None when the layout does not compile or holds no such role
   """
   from . import record   # local: record imports progression, which imports the structure modules
   layout, _error = record.compile_record(doc)
   if layout is None or _bc().role_info(layout, SELECTOR_ROLE) is None:
      return None
   return int(_bc().role_max_value(layout, SELECTOR_ROLE))


def _index(doc: Document, name: str) -> int:
   """!A slot's index.
   @param doc   any manifest Document of the battle
   @param name  slot name
   @return the index
   @throws DocumentError when there is no such slot
   """
   names = slot_names(doc)
   if name not in names:
      raise DocumentError(f"no passive slot {name!r} (slots: {', '.join(names)})")
   return names.index(name)


def _member_slot(member: JsonDict, names: list[str]) -> int | None:
   """!The slot index a party member names.
   @param member  the member
   @param names   slot names
   @return its index (the first slot when it names none), or None for a value naming no slot
   """
   v = member.get(MEMBER_KEY, 0)
   if isinstance(v, str):
      return names.index(v) if v in names else None
   return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < len(names) else None


def _members(doc: Document) -> list[tuple[str, JsonDict]]:
   """!Every party member of the battle data.
   @param doc  any manifest Document of the battle
   @return [(party name, member dict)]
   """
   out = []
   for party in battle.entries(doc, "parties"):
      for m in party.get("members", []) if isinstance(party.get("members"), list) else []:
         if isinstance(m, dict):
            out.append((str(party.get("name")), m))
   return out


def slot_rows(doc: Document) -> list[SlotRow]:
   """!The slots with what names them.
   @param doc  any manifest Document of the battle
   @return one row per slot
   """
   names = slot_names(doc)
   species = [list(s.get(SPECIES_KEY) or []) for s in battle.entries(doc, "species")
              if isinstance(s.get(SPECIES_KEY) or [], list)]
   members = [_member_slot(m, names) for _party, m in _members(doc)]
   return [SlotRow(index=i, name=e[NAME_KEY], rolled=e[ROLLED_KEY],
                   species=sum(1 for ab in species if len(ab) > i and ab[i] is not None),
                   members=sum(1 for k in members if k == i))
           for i, e in enumerate(slots(doc))]


def users(doc: Document, name: str) -> list[str]:
   """!What names a slot: species with a passive in it, party members having it.
   @param doc   any manifest Document of the battle
   @param name  slot name
   @return "species X" / "party P member n" strings
   """
   i = _index(doc, name)
   names = slot_names(doc)
   out = [f"species {s.get('name')}" for s in battle.entries(doc, "species")
          if isinstance(s.get(SPECIES_KEY), list) and len(s[SPECIES_KEY]) > i and s[SPECIES_KEY][i] is not None]
   for party in battle.entries(doc, "parties"):
      members = party.get("members") if isinstance(party.get("members"), list) else []
      out += [f"party {party.get('name')} member {n}" for n, m in enumerate(members)
              if isinstance(m, dict) and MEMBER_KEY in m and _member_slot(m, names) == i]
   return out


# -- the engine's compile ---------------------------------------------------------------------------------------------

def compile_check(doc: Document, targets: list[str] | None = None) -> tuple[list[JsonDict] | None, str | None]:
   """!Compiles the passive slots with the engine's compile_passive_slots() (the smallest limit of the targets).
   @param doc      any manifest Document of the battle
   @param targets  platforms whose caps apply, or None for the default targets
   @return (compiled slots or None, the compiler's message or None)
   """
   bc = _bc()
   try:
      given = bc.strip(copy.deepcopy(battle.data_of(doc, SLOTS_KEY).get(SLOTS_KEY)))
      return bc.compile_passive_slots(given, max_slots(targets), WHERE), None
   except Exception as e:   # ManifestError, DocumentError, type errors in odd data
      return None, str(e)


def _project_error(project: BattleProject | None) -> str | None:
   """!The battle data's compile error as the Documents hold it now.
   @param project  BattleProject, or None
   @return the message, or None (it compiles, or no project)
   """
   return project.error_now() if project is not None else None


def _guarded(doc: Document, change: Callable[[], Any]) -> Any:
   """!Runs a change; refuses it with the engine's message when the slots (or the whole battle data) compiled
   before and do not after (raised inside the edit, which puts the manifests back).
   @param doc     any manifest Document of the battle
   @param change  the change
   @return what change() returned
   @throws DocumentError with the engine's message
   """
   targets = stats.project_targets(doc.path)
   project = logic.project_of(doc)
   _slots, slots_before = compile_check(doc, targets)
   whole_before = _project_error(project)
   result = change()
   _slots, error = compile_check(doc, targets)
   if slots_before is None and error is not None:
      raise DocumentError(error)
   if whole_before is None:
      error = _project_error(project)
      if error is not None:
         raise DocumentError(error)
   return result


def _live(doc: Document) -> list[JsonDict]:
   """!The slot list for editing (the default list written when the structure states none).
   @param doc  any manifest Document of the battle
   @return the live list
   """
   data = battle.data_of(doc, SLOTS_KEY)
   if not isinstance(data.get(SLOTS_KEY), list):
      data[SLOTS_KEY] = default_slots()
   return data[SLOTS_KEY]


def _check_name(doc: Document, name: Any, current: str | None = None) -> str:
   """!A slot name: a lower-case identifier (the engine's PASSIVE_SLOT_NAME) no other slot has.
   @param doc      any manifest Document of the battle
   @param name     the wanted name
   @param current  the name being renamed, or None
   @return the name (stripped)
   @throws DocumentError when it is not one
   """
   pattern = engine.tool("battlec.content").PASSIVE_SLOT_NAME
   if not isinstance(name, str) or not pattern.match(name.strip()):
      raise DocumentError(f"a passive slot's name is a lower-case identifier (got {name!r})")
   name = name.strip()
   if name != current and name in slot_names(doc):
      raise DocumentError(f"there is already a passive slot {name!r}")
   return name


def _remap_members(doc: Document, remap: Callable[[int], int | None], label: str) -> None:
   """!Renumbers the party members' slot numbers (a name stays a name) and the saved bench scenarios' members'.
   @param doc    any manifest Document of the battle
   @param remap  old index -> new index, or None: the slot went (the member falls back to the first)
   @param label  undo label of the bench scenarios' edits
   @return None
   """
   names = slot_names(doc)
   for _party, m in _members(doc):
      v = m.get(MEMBER_KEY)
      if isinstance(v, int) and not isinstance(v, bool):
         new = remap(v)
         if new is None:
            m.pop(MEMBER_KEY)
         else:
            m[MEMBER_KEY] = new
      elif isinstance(v, str) and v not in names:
         m.pop(MEMBER_KEY)   # its slot went
   from .. import bench   # local: core.bench imports core.battle
   bench.follow_passive_slots(logic.project_of(doc), remap, label)


def _species_passives(doc: Document) -> list[JsonDict]:
   """!The species whose passives are a list (the ones an edit of the slots rewrites).
   @param doc  any manifest Document of the battle
   @return species dicts
   """
   return [s for s in battle.entries(doc, "species") if isinstance(s.get(SPECIES_KEY), list)]


def _trimmed(passives: list[Any]) -> list[Any]:
   """!A species' passives without trailing empty slots (inner ones stay as null).
   @param passives  the list
   @return the trimmed list
   """
   out = list(passives)
   while out and out[-1] is None:
      out.pop()
   return out


# -- editing (inside one edit()) -------------------------------------------------------------------------------------

def add_slot(doc: Document, name: str, rolled: bool = True, index: int | None = None) -> int:
   """!Adds a passive slot (the species' passives and the members' numbers after it move with it).
   @param doc     any manifest Document of the battle
   @param name    the slot's name
   @param rolled  the generation list may roll it
   @param index   position, or None for the end
   @return its index
   @throws DocumentError for a taken or invalid name, a full list, or data the engine then refuses
   """
   name = _check_name(doc, name)
   most = max_slots(stats.project_targets(doc.path))
   if slot_count(doc) >= most:
      raise DocumentError(f"at most {most} passive slots (the engine's limit on every target)")
   at = slot_count(doc) if index is None else max(0, min(slot_count(doc), int(index)))

   def change() -> int:
      """!Inserts the slot; the species' passives and the members' numbers from it on move one place down.
      @return its index
      """
      entry: JsonDict = {NAME_KEY: name}
      if rolled != default_rolled():
         entry[ROLLED_KEY] = bool(rolled)
      for s in _species_passives(doc):
         if len(s[SPECIES_KEY]) > at:
            s[SPECIES_KEY] = _trimmed(s[SPECIES_KEY][:at] + [None] + s[SPECIES_KEY][at:])
      _remap_members(doc, lambda k: k + 1 if k >= at else k, "Add passive slot")
      _live(doc).insert(at, entry)
      return at

   return _guarded(doc, change)


def remove_slot(doc: Document, name: str) -> list[str]:
   """!Removes a passive slot: its place goes from every species' passives; the members having it fall back to
   the first slot. The last slot cannot go (a structure has at least one).
   @param doc   any manifest Document of the battle
   @param name  slot name
   @return what lost the slot ("species X", "party P member n")
   @throws DocumentError for the last slot or data the engine then refuses
   """
   i = _index(doc, name)
   if slot_count(doc) <= 1:
      raise DocumentError("a structure has at least one passive slot")
   lost = users(doc, name)

   def change() -> None:
      """!Drops the slot and its place in the species' passives; renumbers the members.
      @return None
      """
      for s in _species_passives(doc):
         if len(s[SPECIES_KEY]) > i:
            s[SPECIES_KEY] = _trimmed(s[SPECIES_KEY][:i] + s[SPECIES_KEY][i + 1:])
      del _live(doc)[i]
      _remap_members(doc, lambda k: None if k == i else (k - 1 if k > i else k), "Remove passive slot")

   _guarded(doc, change)
   return lost


def rename_slot(doc: Document, old: str, new: str) -> int:
   """!Renames a passive slot; the members naming it by name follow.
   @param doc  any manifest Document of the battle
   @param old  current name
   @param new  new name
   @return members updated
   """
   i = _index(doc, old)
   new = _check_name(doc, new, old)
   if new == old:
      return 0

   def change() -> int:
      """!Renames the slot and the members naming it.
      @return members updated
      """
      n = 0
      for _party, m in _members(doc):
         if m.get(MEMBER_KEY) == old:
            m[MEMBER_KEY] = new
            n += 1
      _live(doc)[i][NAME_KEY] = new
      return n

   return _guarded(doc, change)


def move_slot(doc: Document, name: str, delta: int) -> bool:
   """!Moves a slot up or down: the species' passives in the two slots and the members' numbers swap with it.
   @param doc    any manifest Document of the battle
   @param name   slot name
   @param delta  -1 up, +1 down
   @return True if it moved
   """
   i = _index(doc, name)
   j = i + delta
   if not 0 <= j < slot_count(doc):
      return False

   def swap(k: int) -> int:
      """!A slot number after the swap.
      @param k  the number before
      @return the number after
      """
      return j if k == i else (i if k == j else k)

   def change() -> None:
      """!Swaps the two slots and their uses.
      @return None
      """
      width = max(i, j) + 1
      for s in _species_passives(doc):
         ab = s[SPECIES_KEY] + [None] * max(0, width - len(s[SPECIES_KEY]))
         ab[i], ab[j] = ab[j], ab[i]
         s[SPECIES_KEY] = _trimmed(ab)
      lst = _live(doc)
      lst[i], lst[j] = lst[j], lst[i]
      _remap_members(doc, swap, "Move passive slot")

   _guarded(doc, change)
   return True


def saved_records_warning(doc: Document, name: str, delta: int | None = None) -> str | None:
   """!What removing or moving a slot does to creature records already saved (C4): they keep the slot number
   their passive_selector role holds, so the number names another slot afterwards (as a species rename leaves
   saved records' species keys behind). The editors ask before the change; the CLI wants --force.
   @param doc    any manifest Document of the battle
   @param name   slot name
   @param delta  -1 / +1 for a move, None for a removal
   @return the warning, or None (nothing moves: the record keeps no slot, the move goes nowhere)
   """
   if selector_max(doc) is None:
      return None
   names = slot_names(doc)
   i = _index(doc, name)
   keep = (f"Saved creature records keep the slot number their {SELECTOR_ROLE} role holds (the data's numbers "
           f"follow, saved games do not)")
   if delta is None:
      # after the removal number k names the slot that was k + 1; the last number names no slot (an empty slot)
      shifted = [f"those of {names[k]!r} the passive of {names[k + 1]!r}" for k in range(i, len(names) - 1)]
      empty = f"those of {names[-1]!r} (number {len(names) - 1}, then no slot) the first filled rolled slot's passive"
      return f"{keep}: after the removal saved creatures get another passive: {'; '.join(shifted + [empty])}."
   j = i + delta
   if not 0 <= j < len(names):
      return None
   return (f"{keep}: after the move saved creatures of slot {i} ({name!r}) get the passive of {names[j]!r} and "
           f"those of slot {j} ({names[j]!r}) the passive of {name!r}.")


def set_rolled(doc: Document, name: str, rolled: bool) -> None:
   """!Whether the generation list may roll a slot (false: only data or logic gives it).
   @param doc     any manifest Document of the battle
   @param name    slot name
   @param rolled  the value
   @return None
   """
   i = _index(doc, name)
   if not isinstance(rolled, bool):
      raise DocumentError(f"rolled: true or false (got {rolled!r})")

   def change() -> None:
      """!Writes the flag (the default left out).
      @return None
      """
      entry = _live(doc)[i]
      if rolled == default_rolled():
         entry.pop(ROLLED_KEY, None)
      else:
         entry[ROLLED_KEY] = rolled

   _guarded(doc, change)


# -- report -----------------------------------------------------------------------------------------------------------

def budget_text(doc: Document, targets: list[str] | None = None) -> str:
   """!The slots against the engine's limit and the record's passive_selector role.
   @param doc      any manifest Document of the battle
   @param targets  platforms, or None for the default targets
   @return e.g. "2/4 passive slots (gba); passive_selector holds 0-15"
   """
   chosen = targets or stats.DEFAULT_TARGETS
   text = f"{slot_count(doc)}/{max_slots(chosen)} passive slots ({', '.join(chosen)})"
   top = selector_max(doc)
   if top is None:
      return text + f"; the record has no {SELECTOR_ROLE} role (every creature has the first slot)"
   need = slot_count(doc) - 1
   verdict = "" if need <= top else f": too narrow for slot {need}"
   return text + f"; {SELECTOR_ROLE} holds 0-{top}{verdict}"


def lines(doc: Document, targets: list[str] | None = None) -> list[str]:
   """!The slots as text (CLI `passive-slot list`), then the budget.
   @param doc      any manifest Document of the battle
   @param targets  platforms, or None for the default targets
   @return lines
   """
   out = [f"{r['index']} {r['name']}: " + ("rolled" if r["rolled"] else "not rolled") +
          f", {r['species']} species, {r['members']} member(s)" for r in slot_rows(doc)]
   if not is_stated(doc):
      out.append("(the engine's default: the structure states no passive_slots)")
   return out + [budget_text(doc, targets)]
