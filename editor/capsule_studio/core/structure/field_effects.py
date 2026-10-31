"""!The timed field effects of battle data (engine F1, D-27 section 2): the structure manifest's "field_effects".

    structure.json  "field_effects": [{"name": "ward", "label": "Ward", "unit": "steps", "stack": "refresh",
                                       "expiry": "The Ward charm's glow fades.", "persists": true}]

An effect runs for a number of the walker's steps or of the game clock's minutes after an item's use_field logic
(`field_effect start NAME N;`), a script (`field_effect start NAME N;` in a `.cscript`) or game code starts it.
Starting it while it runs follows its stack rule (refresh: start over, add: add the amount, refuse: nothing, the
item is not used up). Effect logic reads it (`field.effect_active(NAME)`, `field.effect_remaining(NAME)`: e.g. in an
`encounter` hook); its expiry message shows when it ends; a save keeps it unless it does not persist. The script
compiler keeps each one in an implicit permanent u16 script variable (`field_effect_<name>`, the save image's script
section) and an implicit expiry script. The names, choices and checks are the engine's (battle_compiler re-exports
battlec/field.py: FIELD_EFFECT_UNITS, FIELD_EFFECT_STACKS, FIELD_EFFECT_DEFAULT_STACK, MAX_FIELD_EFFECTS,
FIELD_EFFECT_MAX_LABEL, FIELD_EFFECT_MAX_EXPIRY, FIELD_EFFECT_MAX_AMOUNT, compile_field_effects(),
field_effect_var(), field_effect_end_script()).

Each editing helper is one change: call it inside one edit() of either manifest. A rename follows the effect logic
naming the effect (core.logic.references()) and (F2) the game's `.cscript` sources naming it (`field_effect start |
active | remaining NAME`, its implicit variable and expiry script: core.scripts.follow_rename(), saved at once and
undone with the edit); a removal is refused while logic names it. An edit that stops data that compiled from compiling
is refused with the engine's message. item_field_effect() / set_item_field_effect() are the Items page's "starts a
field effect" row (an item's `on use_field` handler).
"""
from __future__ import annotations

import copy
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypedDict

from .. import battle, engine, logic
from ..document import Document, DocumentError

if TYPE_CHECKING:
   from ..battle import BattleProject

## A parsed JSON object.
JsonDict = dict[str, Any]

## The structure manifest's list of field effects.
EFFECTS_KEY = "field_effects"
## An effect's name.
NAME_KEY = "name"
## What menus show.
LABEL_KEY = "label"
## Steps or minutes.
UNIT_KEY = "unit"
## What starting it while it runs does.
STACK_KEY = "stack"
## The message shown when it ends.
EXPIRY_KEY = "expiry"
## Whether a save keeps it.
PERSISTS_KEY = "persists"
## Whether an effect persists when it states nothing (battlec/field.py compile_field_effects()).
DEFAULT_PERSISTS = True
## The effect compiler's list effect logic names a field effect from.
LOGIC_LISTS = (EFFECTS_KEY,)
## Location the compiler's messages name.
WHERE = "structure"
## Undo label of the effect logic's part of a rename.
RENAME_LABEL = "Rename field effect"
## The item hook that starts a field effect.
USE_HOOK = "use_field"
## The primitive (and its mode) that starts one.
PRIMITIVE = "field_effect"
## Its mode word.
START_MODE = "start"
## The amount the Items page offers first.
DEFAULT_AMOUNT = 100


class EffectRow(TypedDict):
   """!One field effect as the page and the CLI show it."""
   ## Position in the list (its FIELD_EFFECT_<NAME> id).
   index: int
   ## Its name.
   name: str
   ## What menus show (the name when it states none).
   label: str
   ## steps or minutes.
   unit: str
   ## refresh, add or refuse.
   stack: str
   ## The expiry message, or "" for none.
   expiry: str
   ## Whether a save keeps it.
   persists: bool
   ## Its implicit script variable.
   var: str
   ## Its implicit expiry script ("" without an expiry message).
   end_script: str
   ## The effect logic naming it ("effects/field.ceffect: item Ward Charm").
   users: list[str]


def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


def units() -> list[str]:
   """!The units an effect counts (the engine's FIELD_EFFECT_UNITS, in capsule::script::FieldEffectUnit order).
   @return names
   """
   return list(_bc().FIELD_EFFECT_UNITS)


def stacks() -> list[str]:
   """!The stack rules (the engine's FIELD_EFFECT_STACKS).
   @return names
   """
   return list(_bc().FIELD_EFFECT_STACKS)


def default_stack() -> str:
   """!The stack rule of an effect that states none (the engine's FIELD_EFFECT_DEFAULT_STACK).
   @return the name
   """
   return str(_bc().FIELD_EFFECT_DEFAULT_STACK)


def script_kinds() -> list[str]:
   """!The script statement's kinds that name an effect (the engine's script compiler FIELD_EFFECT_KINDS).
   @return words
   """
   return list(engine.tool("script_compiler").FIELD_EFFECT_KINDS)


def max_effects() -> int:
   """!The most field effects (the engine's MAX_FIELD_EFFECTS).
   @return it
   """
   return int(_bc().MAX_FIELD_EFFECTS)


def max_label() -> int:
   """!The longest label (the engine's FIELD_EFFECT_MAX_LABEL).
   @return letters
   """
   return int(_bc().FIELD_EFFECT_MAX_LABEL)


def max_expiry() -> int:
   """!The longest expiry message (the engine's FIELD_EFFECT_MAX_EXPIRY).
   @return letters
   """
   return int(_bc().FIELD_EFFECT_MAX_EXPIRY)


def max_amount() -> int:
   """!The most steps or minutes an effect holds (the engine's FIELD_EFFECT_MAX_AMOUNT: its u16 variable).
   @return it
   """
   return int(_bc().FIELD_EFFECT_MAX_AMOUNT)


def effects(doc: Document | None) -> list[JsonDict]:
   """!The records in order (live).
   @param doc  any manifest Document of the battle, or None
   @return record dicts (entries that are not objects with a name are left out)
   """
   if doc is None:
      return []
   given = battle.data_of(doc, EFFECTS_KEY).get(EFFECTS_KEY)
   return [e for e in given if isinstance(e, dict) and isinstance(e.get(NAME_KEY), str)] \
      if isinstance(given, list) else []


def effect_names(doc: Document | None) -> list[str]:
   """!The record names in order.
   @param doc  any manifest Document of the battle, or None
   @return names
   """
   return [e[NAME_KEY] for e in effects(doc)]


def users(doc: Document, name: str) -> list[str]:
   """!The effect logic owners naming a record.
   @param doc   any manifest Document of the battle
   @param name  record name
   @return "FILE: KIND NAME" strings
   """
   return logic.per_owner(logic.references(doc, LOGIC_LISTS, name))


def effect_rows(doc: Document) -> list[EffectRow]:
   """!The records with their defaults filled in, their implicit script names and their users.
   @param doc  any manifest Document of the battle
   @return one row per record
   """
   bc = _bc()
   out = []
   for i, e in enumerate(effects(doc)):
      name = e[NAME_KEY]
      expiry = e.get(EXPIRY_KEY)
      out.append(EffectRow(index=i, name=name, label=str(e.get(LABEL_KEY, name)), unit=str(e.get(UNIT_KEY, "")),
                           stack=str(e.get(STACK_KEY, default_stack())),
                           expiry=expiry if isinstance(expiry, str) else "",
                           persists=bool(e.get(PERSISTS_KEY, DEFAULT_PERSISTS)), var=bc.field_effect_var(name),
                           end_script=bc.field_effect_end_script(name) if isinstance(expiry, str) else "",
                           users=users(doc, name)))
   return out


def compile_check(doc: Document) -> tuple[list[JsonDict] | None, str | None]:
   """!Compiles the records with the engine's compile_field_effects().
   @param doc  any manifest Document of the battle
   @return (compiled records or None, the compiler's message or None)
   """
   bc = _bc()
   try:
      given = bc.strip(copy.deepcopy(battle.data_of(doc, EFFECTS_KEY).get(EFFECTS_KEY)))
      return bc.compile_field_effects(given, WHERE), None
   except Exception as e:   # ManifestError, type errors in odd data
      return None, str(e)


def _guarded(doc: Document, change: Callable[[], Any]) -> Any:
   """!Runs a change; refuses it with the engine's message when the records (or the whole battle data) compiled
   before and do not after.
   @param doc     any manifest Document of the battle
   @param change  the change
   @return what change() returned
   @throws DocumentError with the engine's message
   """
   project = logic.project_of(doc)
   _compiled, before = compile_check(doc)
   whole_before = project.error_now() if project is not None else None
   result = change()
   _compiled, error = compile_check(doc)
   if before is None and error is not None:
      raise DocumentError(error)
   if whole_before is None and project is not None:
      error = project.error_now()
      if error is not None:
         raise DocumentError(error)
   return result


def _live(doc: Document) -> list[JsonDict]:
   """!The record list for editing (written when the structure states none).
   @param doc  any manifest Document of the battle
   @return the live list
   """
   data = battle.data_of(doc, EFFECTS_KEY)
   if not isinstance(data.get(EFFECTS_KEY), list):
      data[EFFECTS_KEY] = []
   return data[EFFECTS_KEY]


def _effect(doc: Document, name: str) -> JsonDict:
   """!One record (live).
   @param doc   any manifest Document of the battle
   @param name  record name
   @return the dict
   @throws DocumentError when there is no such record
   """
   for e in effects(doc):
      if e[NAME_KEY] == name:
         return e
   raise DocumentError(f"no field effect {name!r} (field effects: {', '.join(effect_names(doc)) or 'none'})")


def _check_name(doc: Document, name: Any, current: str | None = None) -> str:
   """!A record name: not empty, no other record's (the engine checks its form: a lower-case identifier).
   @param doc      any manifest Document of the battle
   @param name     the wanted name
   @param current  the name being renamed, or None
   @return the name (stripped)
   @throws DocumentError when it is not one
   """
   name = name.strip() if isinstance(name, str) else name
   if not isinstance(name, str) or not name:
      raise DocumentError("a field effect needs a name")
   if name != current and name in effect_names(doc):
      raise DocumentError(f"there is already a field effect {name!r}")
   return name


def add_effect(doc: Document, name: str, unit: str | None = None, at: int | None = None) -> None:
   """!Adds a record (the engine's defaults: refreshes, no expiry message, persists).
   @param doc   any manifest Document of the battle
   @param name  its name
   @param unit  steps or minutes (None: the engine's first unit)
   @param at    its position (None: last)
   @return None
   """
   name = _check_name(doc, name)
   unit = units()[0] if unit is None else unit
   if unit not in units():
      raise DocumentError(f"unit: one of {', '.join(units())} (got {unit!r})")
   if len(effects(doc)) >= max_effects():
      raise DocumentError(f"at most {max_effects()} field effects")

   def change() -> None:
      """!Inserts it."""
      live = _live(doc)
      live.insert(len(live) if at is None else max(0, min(at, len(live))), {NAME_KEY: name, UNIT_KEY: unit})
   _guarded(doc, change)


def remove_effect(doc: Document, name: str) -> None:
   """!Removes a record (refused while effect logic names it).
   @param doc   any manifest Document of the battle
   @param name  record name
   @return None
   """
   _effect(doc, name)
   named = users(doc, name)
   if named:
      raise DocumentError(f"field effect {name!r} is used by {', '.join(named)}")
   _guarded(doc, lambda: _live(doc).remove(_effect(doc, name)))


def rename_effect(doc: Document, old: str, new: str, follow: bool = True) -> list[str]:
   """!Renames a record; the effect logic naming it follows (its label too while it was the name).
   @param doc     any manifest Document of the battle
   @param old     its name
   @param new     the new name
   @param follow  False to leave the game's scripts to follow_scripts() (C8: the CLI follows them only once the
                  renamed battle data compiled and was saved)
   @return the logic places rewritten, then the "scripts: ..." ones
   """
   new = _check_name(doc, new, old)
   e = _effect(doc, old)

   def change() -> list[str]:
      """!Renames it and its users."""
      e[NAME_KEY] = new
      return logic.references(doc, LOGIC_LISTS, old, new, RENAME_LABEL)
   places = _guarded(doc, change)
   return places + (follow_scripts(doc, old, new) if follow else [])


def follow_scripts(doc: Document, old: str, new: str) -> list[str]:
   """!The game's scripts follow a rename (F2, F1 leftover: `field_effect ... NAME`, its implicit variable and
   expiry script; saved at once, undone with the edit group).
   @param doc  any manifest Document of the battle
   @param old  the old name
   @param new  the new name
   @return "scripts: ..." places
   """
   from .. import scripts
   bc = _bc()
   project = logic.project_of(doc)
   manifest = project.scripts_manifest() if project is not None else None
   follow = scripts.follow_rename(manifest, engine.tool("script_compiler").FIELD_EFFECT_WORD, script_kinds(), old, new,
                                  [(bc.field_effect_var(old), bc.field_effect_var(new)),
                                   (bc.field_effect_end_script(old), bc.field_effect_end_script(new))])
   return [f"scripts: {place}" for place in follow]


def move_effect(doc: Document, name: str, delta: int) -> None:
   """!Moves a record up or down (the FIELD_EFFECT_<NAME> ids follow the order).
   @param doc    any manifest Document of the battle
   @param name   record name
   @param delta  -1 up, +1 down
   @return None
   """
   names = effect_names(doc)
   if name not in names:
      raise DocumentError(f"no field effect {name!r}")
   i = names.index(name)
   j = i + delta
   if not 0 <= j < len(names):
      return

   def change() -> None:
      """!Swaps it with its neighbour."""
      live = _live(doc)
      live[i], live[j] = live[j], live[i]
   _guarded(doc, change)


def _set_key(doc: Document, name: str, key: str, value: Any, default: Any) -> None:
   """!Writes one key of a record (its default value: the key goes).
   @param doc      any manifest Document of the battle
   @param name     record name
   @param key      the key
   @param value    the value
   @param default  the value the engine takes when the key is left out
   @return None
   """
   e = _effect(doc, name)

   def change() -> None:
      """!Writes it."""
      if value == default:
         e.pop(key, None)
      else:
         e[key] = value
   _guarded(doc, change)


def set_label(doc: Document, name: str, label: str) -> None:
   """!Sets what menus show (the name, or empty: the key goes).
   @param doc    any manifest Document of the battle
   @param name   record name
   @param label  1 to max_label() letters
   @return None
   """
   label = label.strip() if isinstance(label, str) else label
   if not isinstance(label, str) or len(label) > max_label():
      raise DocumentError(f"a label is at most {max_label()} letters")
   _set_key(doc, name, LABEL_KEY, label or name, name)


def set_unit(doc: Document, name: str, unit: str) -> None:
   """!Sets what an effect counts.
   @param doc   any manifest Document of the battle
   @param name  record name
   @param unit  one of units()
   @return None
   """
   if unit not in units():
      raise DocumentError(f"unit: one of {', '.join(units())} (got {unit!r})")
   # the unit has no default: it is always written
   _set_key(doc, name, UNIT_KEY, unit, None)


def set_stack(doc: Document, name: str, stack: str) -> None:
   """!Sets what starting an effect while it runs does.
   @param doc    any manifest Document of the battle
   @param name   record name
   @param stack  one of stacks()
   @return None
   """
   if stack not in stacks():
      raise DocumentError(f"stack: one of {', '.join(stacks())} (got {stack!r})")
   _set_key(doc, name, STACK_KEY, stack, default_stack())


def set_expiry(doc: Document, name: str, message: str) -> None:
   """!Sets the message shown when an effect ends (empty: none, the key goes).
   @param doc      any manifest Document of the battle
   @param name     record name
   @param message  0 to max_expiry() letters
   @return None
   """
   message = message.strip() if isinstance(message, str) else message
   if not isinstance(message, str) or len(message) > max_expiry():
      raise DocumentError(f"an expiry message is at most {max_expiry()} letters")
   _set_key(doc, name, EXPIRY_KEY, message or None, None)


def set_persists(doc: Document, name: str, persists: bool) -> None:
   """!Sets whether a save keeps an effect.
   @param doc       any manifest Document of the battle
   @param name      record name
   @param persists  true: it survives a save and a load
   @return None
   """
   _set_key(doc, name, PERSISTS_KEY, bool(persists), DEFAULT_PERSISTS)


def lines(doc: Document) -> list[str]:
   """!The records as text (the CLI's `field-effect list`).
   @param doc  any manifest Document of the battle
   @return one line per record
   """
   out = []
   for r in effect_rows(doc):
      out.append(f"{r['name']} ({r['label']}): {r['unit']}, {r['stack']}, "
                 f"{'persists' if r['persists'] else 'ends on load'}; ends with "
                 f"{repr(r['expiry']) if r['expiry'] else 'no message'}; variable {r['var']}; used by "
                 f"{', '.join(r['users']) or 'nobody'}")
   return out


# -- items starting an effect -----------------------------------------------------------------------------------------

def _is_start(statement: Any) -> bool:
   """!Whether a parsed statement starts a field effect.
   @param statement  a statement node
   @return True for `field_effect start NAME N;`
   """
   return isinstance(statement, dict) and statement.get("stmt") == PRIMITIVE and statement.get("mode") == START_MODE


def item_field_effect(project: BattleProject, item: str) -> tuple[str, str] | None:
   """!The field effect an item's use_field logic starts.
   @param project  BattleProject
   @param item     item name
   @return (effect, amount as text) of its first `field_effect start`, or None
   """
   ref = f"item{logic.OWNER_SEPARATOR}{item}"
   if not any(r.kind == "item" and r.name == item for r in logic.owners(project, "item")):
      return None
   for h in logic.owner_ast(project, ref).get("handlers", []):
      if h.get("on") != USE_HOOK:
         continue
      for s in h.get("body", []):
         if _is_start(s):
            return str(s.get("effect")), logic.format_expression(s.get("amount"))
   return None


def set_item_field_effect(project: BattleProject, item: str, effect: str, amount: int,
                          label: str = "Item field effect") -> None:
   """!Makes an item start a field effect: its use_field handler gets `field_effect start EFFECT AMOUNT;` (one that
   starts one already gets the new effect and amount; other code in it stays, the start last), its use grows to
   field use (inside an edit() of the battle manifest).
   @param project  BattleProject
   @param item     item name
   @param effect   one of effect_names()
   @param amount   steps or minutes (1 to max_amount())
   @param label    undo label of the logic edit
   @return None
   @throws DocumentError for an unknown effect, an amount out of range, or data the engine then refuses
   """
   from .. import inventory   # local: core.inventory imports core.structure
   doc = project.battle
   if effect not in effect_names(doc):
      raise DocumentError(f"no field effect {effect!r} (field effects: {', '.join(effect_names(doc)) or 'none'})")
   if not isinstance(amount, int) or isinstance(amount, bool) or not 1 <= amount <= max_amount():
      raise DocumentError(f"a field effect runs 1 to {max_amount()} steps or minutes (got {amount!r})")

   def change() -> None:
      """!Writes the use and the handler."""
      e = battle.entry(doc, "items", item)
      use = inventory.fields_of(doc, item)[inventory.USE_KEY]
      if USE_HOOK not in inventory.hooks_needed(use):
         grown = set(inventory.hooks_needed(use)) | {USE_HOOK}
         e[inventory.USE_KEY] = next(u for u in inventory.uses() if set(inventory.hooks_needed(u)) == grown)
      ref = f"item{logic.OWNER_SEPARATOR}{item}"
      if not any(r.kind == "item" and r.name == item for r in logic.owners(project, "item")):
         logic.add_owner(project, "item", item, label=label)
      ast = logic.owner_ast(project, ref)
      statement = logic.parse_statement(f"{PRIMITIVE} {START_MODE} {logic.format_id(effect)} {amount};")
      handlers = ast.setdefault("handlers", [])
      h = next((h for h in handlers if h.get("on") == USE_HOOK), None)
      if h is None:
         handlers.append({"on": USE_HOOK, "body": [statement]})
      else:
         stub = [logic.parse_statement(inventory.NEW_USE_BODY)]
         h["body"] = [s for s in h.get("body", []) if s not in stub and not _is_start(s)] + [statement]
      logic.set_owner_ast(project, ref, ast, label)
   _guarded(doc, change)
