"""!The creature record of battle data (§3.2 "Record"):
the battle manifest's "monster_layout", edited role by role.

    "monster_layout": ["species_key", "seed", {"role": "stat_genes", "width": 4}, ...,
                       {"custom": "friendship", "width": 8, "default": 70}]

or the object form, which battle data must use since the stage scaling (a
battle states its party size)

    "monster_layout": {"party_size": 3, "move_slots": 6, "roles": [...]}

The studio writes only the object form: the first edit of an older list
form converts it, stating the party size (the engine's registry count when
it gave none), and a manifest without a layout gets an object. Engine roles have fixed IDs (their
place in the engine's registry, battlec.layout.ROLES); a layout may choose
the width of some (up to the engine's maximum, ROLE_MAX_WIDTHS) and the
count of the "chosen" ones (ROLE_MAX_COUNTS); per-stat roles hold one
element per stat and move roles one per move slot. Custom roles (name,
width, count, default) get the IDs 0x80 + their index among the custom
roles, so moving one changes its ID. A bare retired role name (owner_secret,
friendship, ...) is the custom role of that name and its old shape.

A custom role with "stored": false is computed on read: the
generation list's one derived or constant entry gives its value whenever it
is read (battle::record_value()), so it never goes stale. It takes no record
bits, is left out of the hash and the transfer, and its ID follows every
stored custom role's (0x80 + stored custom roles + its index among the
unstored ones). set_stored() turns it on or off; it is only allowed while
the role has exactly one derived or constant generation entry (the engine's
UNSTORED_KINDS), and field scripts read an unstored role as 0.

The record's size, bit offsets and hash always come from the engine's own
battlec.layout.compile_layout(); nothing here packs or hashes. The budget is
the record's bytes against each target platform's limit (the engine's
build_settings.PLATFORM_LIMITS; the game's targets: its reference/
project.json "targets"). A layout hash other than the last saved file's
means saves made with the old layout no longer load.

Each editing helper is one change: call it inside one battle.edit() and Undo
takes it back. The helpers refuse what the engine's compiler refuses (with
its limits), and an edit that would make a compiling layout stop compiling
is refused with the compiler's message.
"""
from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import battle, engine, logic, manifest_io
from ..document import Document, DocumentError
from . import progression
from . import resources as resource_model
from . import stats as stat_model

## A parsed JSON object.
JsonDict = dict[str, Any]
## One role as role_rows() gives it (see role_rows()).
RoleRow = dict[str, Any]
## One target's record budget: (platform, bytes used, most bytes).
Budget = tuple[str, int, int]
## A layout report (see layout_report()).
LayoutReport = dict[str, Any]

## The battle manifest's record layout.
LAYOUT_KEY = "monster_layout"
## The object form's role list.
ROLES_KEY = "roles"
## The object form's party size.
PARTY_SIZE_KEY = "party_size"
## The object form's move slots.
MOVE_SLOTS_KEY = "move_slots"
## Key naming an engine role in an object entry.
ROLE_KEY = "role"
## Key naming a custom role.
CUSTOM_KEY = "custom"
## Key of a role's element width.
WIDTH_KEY = "width"
## Key of a role's element count.
COUNT_KEY = "count"
## Key of a custom role's default value.
DEFAULT_KEY = "default"
## Key of a custom role's "the record holds it" flag (false = computed on read).
STORED_KEY = "stored"
## Properties set_role() changes.
ROLE_PROPERTIES = (WIDTH_KEY, COUNT_KEY, DEFAULT_KEY)
## Kind of an engine role row.
KIND_ENGINE = "engine"
## Kind of a custom role row.
KIND_CUSTOM = "custom"
## Kind of a row the engine knows no role for (the compiler reports it).
KIND_UNKNOWN = "unknown"
## Count rule of a custom role's row (the engine's rules are battlec.layout.COUNT_RULES).
COUNT_RULE_CUSTOM = "custom"
## The engine's count rule of a per-stat role.
COUNT_RULE_STAT = "stat"
## The engine's count rule of a move role.
COUNT_RULE_MOVE = "move"
## The engine's count rule of a role whose count the layout chooses.
COUNT_RULE_CHOSEN = "chosen"
## The engine's count rule of a retired role (a custom role now).
COUNT_RULE_RETIRED = "retired"
## Most record bytes the layout is compiled with here: capsule::monster::Layout::record_bytes is 16 bits, so
## the size is always computed; each target's own limit is checked by the budget.
UNBOUNDED_RECORD_BYTES = 0xFFFF
## Location the compiler's messages name.
WHERE = LAYOUT_KEY
## Shown in the transfer column of a custom role when the engine has no record transfer keys.
TRANSFER_PENDING = "(transfer v2)"
## Shown in the transfer column of an engine role that is not per stat: a transfer finds it by its fixed ID.
TRANSFER_BY_ID = "by ID"
## Shown in the transfer column of an unstored custom role (not transferred; the receiver computes it).
TRANSFER_UNSTORED = "(computed on read: not transferred)"
## The effect compiler's structure list of the roles effect logic names (`holder.role(NAME)`).
ROLE_LISTS = ("roles",)
## Script statements that name a record role (the engine's script compiler: role_get / role_set).
ROLE_STATEMENTS = ("role_get", "role_set")
## A scripts manifest's field placeholders.
PLACEHOLDERS_KEY = "placeholders"
## Binding of a field placeholder to a record role (with its party "slot").
PLACEHOLDER_RECORD_KEY = "record"
## A scripts manifest's script sources.
SOURCES_KEY = "sources"
## A scripts manifest's battle manifest (whose record its role_get / role_set read).
SCRIPTS_BATTLE_KEY = "battle"
## The project manifest's key of the scripts manifest (core.project.GAME_FILES).
SCRIPTS_FILE_KEY = "scripts"
## The per-stat role holding a creature's genes.
GENES_ROLE = "stat_genes"
## The per-stat role holding a creature's training values.
TRAINING_ROLE = "stat_training"
## The per-stat role holding a creature's awakening values.
AWAKEN_ROLE = "stat_awaken"
## The terms concept naming each per-stat input (the engine's TERMS: genes, training, awaken).
STAT_INPUT_TERMS = {"gene": "genes", "training": "training", "awaken": "awaken"}


def _lay() -> Any:
   """!The engine's record layout names, as battle_compiler re-exports them (battlec.layout's).
   @return battle_compiler
   """
   return engine.tool("battle_compiler")


def _layout() -> Any:
   """!The engine's record layout module, for the names battle_compiler does not re-export (MAX_ROLE_BITS,
   ROLE_SHAPES, CUSTOM_NAME, the transfer keys role_key(), stat_key() and ROLE_KEY_PREFIX).
   @return battlec.layout
   """
   return engine.tool("battlec.layout")


def _limits(platform: str) -> dict[str, int]:
   """!One platform's engine limits.
   @param platform  build_settings platform name
   @return {"max_stats", "max_record_bytes", "max_party_size"}
   @throws DocumentError for an unknown platform
   """
   bs = engine.tool("build_settings")
   try:
      return bs.platform_limits(platform)
   except bs.SettingsError as e:
      raise DocumentError(str(e)) from None


def _is_int(value: Any) -> bool:
   """!Whether a JSON value is an integer (not a bool).
   @param value  the value
   @return True for an int
   """
   return isinstance(value, int) and not isinstance(value, bool)


def _int_in(value: Any, lo: int, hi: int, what: str) -> int:
   """!An integer within bounds.
   @param value  the value
   @param lo     lowest
   @param hi     highest
   @param what   what it is (for the message)
   @return the value
   @throws DocumentError when it is not one
   """
   if not _is_int(value) or not lo <= value <= hi:
      raise DocumentError(f"{what}: a whole number from {lo} to {hi} (got {value!r})")
   return value


# -- reading ----------------------------------------------------------------------------------------------------------

def layout_value(doc: Document) -> Any:
   """!The manifest's monster_layout as written.
   @param doc  battle Document
   @return the list, the object, or None
   """
   return battle.data_of(doc, LAYOUT_KEY).get(LAYOUT_KEY)


def party_size_stated(doc: Document) -> bool:
   """!Whether the layout states its party size (the engine requires it since the stage scaling).
   @param doc  battle Document
   @return True for an object form with "party_size"
   """
   given = layout_value(doc)
   return isinstance(given, dict) and _is_int(given.get(PARTY_SIZE_KEY))


def move_slots_stated(doc: Document) -> bool:
   """!Whether the layout states its move slots (the engine requires it since the resources: battlec LAYOUT_REQUIRED).
   @param doc  battle Document
   @return True for an object form with "move_slots"
   """
   given = layout_value(doc)
   return isinstance(given, dict) and _is_int(given.get(MOVE_SLOTS_KEY))


def is_object_form(doc: Document) -> bool:
   """!Whether the layout is the v2 object form.
   @param doc  battle Document
   @return True for {"party_size", "move_slots", "roles"}
   """
   return isinstance(layout_value(doc), dict)


def _listed(doc: Document) -> list[Any]:
   """!The role entries for reading (nothing created).
   @param doc  battle Document
   @return the live list, or []
   """
   given = layout_value(doc)
   if isinstance(given, dict):
      given = given.get(ROLES_KEY)
   return given if isinstance(given, list) else []


def _entries(doc: Document) -> list[Any]:
   """!The role entries for editing (the layout is written in the object form first, see _object_form()).
   @param doc  battle Document
   @return the live list
   """
   given = _object_form(doc)
   if not isinstance(given.get(ROLES_KEY), list):
      given[ROLES_KEY] = []
   return given[ROLES_KEY]


def entry_name(entry: Any) -> str | None:
   """!The role an entry names.
   @param entry  a monster_layout entry
   @return its name, or None for an entry that names none
   """
   if isinstance(entry, str):
      return entry
   if isinstance(entry, dict):
      name = entry.get(CUSTOM_KEY, entry.get(ROLE_KEY))
      return name if isinstance(name, str) else None
   return None


def _is_custom(entry: Any) -> bool:
   """!Whether an entry is a custom role (a {"custom"} entry or a bare retired role name).
   @param entry  a monster_layout entry
   @return True for a custom role
   """
   return (isinstance(entry, dict) and CUSTOM_KEY in entry) or \
      (isinstance(entry, str) and entry in _lay().RETIRED_ROLES)


def is_stored(entry: Any) -> bool:
   """!Whether the record holds a role (every role but a custom role with "stored": false).
   @param entry  a monster_layout entry
   @return False for an unstored custom role
   """
   return not (isinstance(entry, dict) and CUSTOM_KEY in entry and entry.get(STORED_KEY, True) is False)


def unstored_roles(doc: Document) -> list[str]:
   """!The unstored custom roles (computed on read), in record order.
   @param doc  battle Document
   @return names
   """
   return [n for n in (entry_name(e) for e in _listed(doc) if not is_stored(e)) if n is not None]


def role_names(doc: Document) -> list[str]:
   """!The roles the layout holds, in record order.
   @param doc  battle Document
   @return names (entries that name none are left out)
   """
   return [n for n in (entry_name(e) for e in _listed(doc)) if n is not None]


def _find(doc: Document, name: str) -> int:
   """!Where a role is in the layout.
   @param doc   battle Document
   @param name  role name
   @return its index in the entries
   @throws DocumentError when the layout does not hold it
   """
   for i, e in enumerate(_listed(doc)):
      if entry_name(e) == name:
         return i
   raise DocumentError(f"the record holds no role {name!r} (roles: {', '.join(role_names(doc)) or 'none'})")


def move_slots(doc: Document) -> int:
   """!The layout's move slots (moves a creature knows).
   @param doc  battle Document
   @return the object form's move_slots, or the engine's default
   """
   given = layout_value(doc)
   value = given.get(MOVE_SLOTS_KEY) if isinstance(given, dict) else None
   return value if _is_int(value) else _lay().DEFAULT_MOVE_SLOTS


def party_size(doc: Document) -> int:
   """!The layout's party size (creatures a party holds).
   @param doc  battle Document
   @return the object form's party_size, or the engine's default
   """
   given = layout_value(doc)
   value = given.get(PARTY_SIZE_KEY) if isinstance(given, dict) else None
   return value if _is_int(value) else _lay().DEFAULT_PARTY_SIZE


def stat_count(doc: Document) -> int:
   """!Elements of each per-stat role: the manifest's stats.
   @param doc  battle Document
   @return count
   """
   return len(battle.stat_keys(doc))


def max_move_slots() -> int:
   """!Most move slots the engine holds (capsule::monster::kMaxMoveSlots; the same on every platform).
   @return count
   """
   return _lay().MAX_MOVE_SLOTS


def default_move_slots() -> int:
   """!Move slots of a layout that names none (capsule::monster::kDefaultMoveSlots).
   @return count
   """
   return _lay().DEFAULT_MOVE_SLOTS


def max_role_bits() -> int:
   """!Widest role element the engine stores (a custom role's widest width).
   @return bits
   """
   return _layout().MAX_ROLE_BITS


def max_custom_count() -> int:
   """!Most elements of a custom role.
   @return count
   """
   return _lay().MAX_CUSTOM_COUNT


def max_party_size(targets: list[str] | None = None) -> int:
   """!Most creatures a party holds on every target (build_settings.PLATFORM_LIMITS).
   @param targets  platforms, or None for the default targets
   @return the smallest limit
   """
   return min(_limits(t)["max_party_size"] for t in (targets or stat_model.DEFAULT_TARGETS))


def max_record_bytes(platform: str) -> int:
   """!Most record bytes the engine stores on a platform.
   @param platform  build_settings platform name
   @return bytes
   """
   return _limits(platform)["max_record_bytes"]


def project_targets(path: str | Path | None) -> list[str]:
   """!The platforms a game builds for (core.structure.stats.project_targets()).
   @param path  any file of the game, or None
   @return the targets
   """
   return stat_model.project_targets(path)


def engine_roles() -> list[str]:
   """!The engine roles a layout may list (the registry without the retired ones), in ID order.
   @return names
   """
   lay = _lay()
   return [n for n in lay.ROLE_NAMES if n not in lay.RETIRED_ROLES]


def free_engine_roles(doc: Document) -> list[str]:
   """!The engine roles the layout does not hold yet.
   @param doc  battle Document
   @return names, in ID order
   """
   held = set(role_names(doc))
   return [n for n in engine_roles() if n not in held]


def required_roles() -> list[str]:
   """!The roles every battle needs (the engine's).
   @return names
   """
   return list(_lay().REQUIRED_ROLES)


def _transfer_keys(doc: Document, name: str, rule: str) -> tuple[list[str] | None, list[int] | None]:
   """!What a record transfer (the engine's battlec/transfer.py, tools/record_transfer.py) finds a role's elements
   by: an engine role by its fixed ID, a per-stat role's elements by the stats' transfer keys (layout.stat_key()),
   a custom role by its name's key (layout.role_key()).
   @param doc   battle Document
   @param name  role name
   @param rule  its count rule
   @return (keys as shown, their 32-bit values); (None, None) for a custom role when the engine has no transfer
           keys (TRANSFER_PENDING)
   """
   lay = _layout()   # role_key / stat_key / ROLE_KEY_PREFIX: not re-exported by battle_compiler
   # Looked up, not imported: an engine without the record transfer still opens (the keys show as pending).
   role_key, stat_key = getattr(lay, "role_key", None), getattr(lay, "stat_key", None)
   if rule in (COUNT_RULE_CUSTOM, COUNT_RULE_RETIRED):
      if role_key is None:
         return None, None
      return [getattr(lay, "ROLE_KEY_PREFIX", "") + name], [role_key(name)]
   if rule == COUNT_RULE_STAT:
      keys = [str(r["transfer"]) for r in stat_model.stat_list(doc)]
      return keys, [stat_key(k) for k in keys] if stat_key is not None else None
   return [TRANSFER_BY_ID], []


def role_rows(doc: Document) -> list[RoleRow]:
   """!Every role of the layout as the Record table shows it.
   @param doc  battle Document
   @return one dict per entry, in record order: index, name, kind (KIND_ENGINE, KIND_CUSTOM, KIND_UNKNOWN),
           id (fixed for an engine role; 0x80 + the stored custom index; an unstored custom role's after every
           stored one's), width, width_max, width_editable, count, count_rule (an engine COUNT_RULES name, or
           COUNT_RULE_CUSTOM), count_max, count_editable, default (custom roles; else None), stored (False for
           an unstored custom role), bits (width x count; 0 for an unstored role: no record bits),
           required, legacy (a bare retired role name), transfer (keys as shown, or None: TRANSFER_PENDING),
           transfer_values (their 32-bit keys, or None)
   """
   lay = _lay()
   rules = {name: rule for name, _w, _n, rule in lay.ROLES}
   slots, stat_n = move_slots(doc), stat_count(doc)
   rows = []
   listed = _listed(doc)
   # unstored custom roles take the IDs after every stored one's (capsule::monster::Layout::unstored_count)
   stored_custom = sum(1 for e in listed if _is_custom(e) and is_stored(e))
   custom_index, unstored_index = 0, 0
   for i, e in enumerate(listed):
      name = entry_name(e)
      given = e if isinstance(e, dict) else {}
      row: RoleRow = {"index": i, "name": name, "default": None, "required": name in lay.REQUIRED_ROLES,
                      "legacy": isinstance(e, str) and name in lay.RETIRED_ROLES, "stored": is_stored(e)}
      if _is_custom(e):
         if row["legacy"]:   # a bare retired name: the custom role of its old shape
            width, count = _layout().ROLE_SHAPES[name]
         else:
            width, count = given.get(WIDTH_KEY), given.get(COUNT_KEY, 1)
         if row["stored"]:
            rid = lay.CUSTOM_ROLE_BASE + custom_index
            custom_index += 1
         else:
            rid = lay.CUSTOM_ROLE_BASE + stored_custom + unstored_index
            unstored_index += 1
         row.update(kind=KIND_CUSTOM, id=rid, width=width,
                    width_max=_layout().MAX_ROLE_BITS, width_editable=True, count=count, count_rule=COUNT_RULE_CUSTOM,
                    count_max=lay.MAX_CUSTOM_COUNT, count_editable=True,
                    default=0 if row["legacy"] else given.get(DEFAULT_KEY, 0))
      elif name in _layout().ROLE_SHAPES:
         reg_width, reg_count = _layout().ROLE_SHAPES[name]
         rule = rules[name]
         count = {COUNT_RULE_STAT: stat_n, COUNT_RULE_MOVE: slots}.get(rule, given.get(COUNT_KEY, reg_count))
         row.update(kind=KIND_ENGINE, id=lay.ROLE_NAMES.index(name), width=given.get(WIDTH_KEY, reg_width),
                    width_max=lay.role_width_max(name), width_editable=name in lay.ROLE_MAX_WIDTHS,
                    count=count, count_rule=rule, count_max=lay.role_count_max(name),
                    count_editable=name in lay.ROLE_MAX_COUNTS)
      else:
         row.update(kind=KIND_UNKNOWN, id=None, width=None, width_max=None, width_editable=False, count=None,
                    count_rule=None, count_max=None, count_editable=False)
      ok = _is_int(row["width"]) and _is_int(row["count"])
      row["bits"] = (row["width"] * row["count"] if row["stored"] else 0) if ok else None
      if row["kind"] == KIND_UNKNOWN or not row["stored"]:
         row["transfer"], row["transfer_values"] = [], []   # an unstored role is not transferred
      else:
         row["transfer"], row["transfer_values"] = _transfer_keys(doc, name, row["count_rule"])
      rows.append(row)
   return rows


# -- field scripts using roles --------------------------------------------------------------------------------------

def _scripts_manifest(doc: Document) -> tuple[Path, JsonDict] | None:
   """!The game's scripts manifest when its scripts use this battle data's record (the project's "scripts"; a
   manifest whose "battle" names another battle manifest reads another record).
   @param doc  battle Document
   @return (scripts.json, its data), or None when there is none
   """
   from .. import codepage, project as projects   # local: core.codepage imports core.battle

   found = codepage.find_project(doc.path) if doc.path is not None else None
   if found is None:
      return None
   try:
      path = projects.game_files(codepage.open_project(found)).get(SCRIPTS_FILE_KEY)
      data = manifest_io.load(path) if path is not None and path.is_file() else None
   except (DocumentError, OSError, ValueError):
      return None   # the project's own pages report a bad manifest
   if not isinstance(data, dict):
      return None
   named = data.get(SCRIPTS_BATTLE_KEY)
   own = battle.content_doc(doc).path   # the scripts name the battle manifest (it names the structure)
   if isinstance(named, str) and (path.parent / named).resolve() != Path(own).resolve():
      return None
   return path, data


def _script_role_refs(text: str, file: str) -> list[tuple[int, str, str]]:
   """!The roles a script source's role_get / role_set statements name, read from the engine script compiler's
   tokens (the way core.codepage reads the scripts' texts).
   @param text  the source
   @param file  its name (for the tokenizer's errors)
   @return [(line, statement, the role token's text: a name or a number)]
   @throws script_compiler.ScriptError when the source does not tokenize
   """
   tokens = engine.tool("script_compiler").tokenize(text, file)
   out = []
   for i, tok in enumerate(tokens):
      opening = i + 1   # the statement's "("
      if tok.kind != "name" or tok.text not in ROLE_STATEMENTS or tokens[opening].text != "(":
         continue
      # The role is the operand after the first top-level comma (the slot operand may hold parentheses: var(x)).
      depth = 0
      for j in range(opening + 1, len(tokens) - 1):
         sym = tokens[j].text if tokens[j].kind == "sym" else None
         if sym == "(":
            depth += 1
         elif sym == ")":
            if depth == 0:
               break
            depth -= 1
         elif sym == "," and depth == 0:
            out.append((tok.line, tok.text, tokens[j + 1].text))
            break
   return out


def _script_number(text: str) -> int | None:
   """!A role named by its ID in a script: a number written in decimal or hex (0x81).
   @param text  the role token's text
   @return the number, or None for a name
   """
   if not text[:1].isdigit():
      return None
   try:
      return int(text, 0)
   except ValueError:   # decimal with leading zeros
      return int(text)


def stored_position_id(doc: Document, name: str) -> int | None:
   """!The ID a custom role has while the record stores it (0x80 + its index among the stored custom roles, the
   roles before it in list order; what an unstored role's ID becomes when it is stored again).
   @param doc   battle Document
   @param name  role name
   @return the ID, or None for an engine role or an unknown name
   """
   rows = role_rows(doc)
   row = next((r for r in rows if r["name"] == name), None)
   if row is None or row["kind"] != KIND_CUSTOM:
      return None
   before = sum(1 for r in rows if r["kind"] == KIND_CUSTOM and r["stored"] and r["index"] < row["index"])
   return _lay().CUSTOM_ROLE_BASE + before


def role_users(doc: Document, name: str, removing: bool = False, storing: bool = False) -> list[str]:
   """!Where the game's field scripts use a role: role_get / role_set statements naming it in the scripts
   manifest's .cscript sources, and field placeholders bound to it ("placeholders": {"x": {"record": name}}).
   Removing or renaming the role breaks them (the editors ask first; the CLI wants --force).
   @param doc       battle Document
   @param name      role name
   @param removing  also list statements naming a custom role by ID from this role's on (removing a custom
                    role moves the IDs of the ones after it down; unstoring it too)
   @param storing   with @p removing: the role is stored again (the IDs move from its stored-position ID on,
                    stored_position_id(), which is below its unstored ID)
   @return one "scripts: ..." line per use (empty when nothing uses it, or the battle data is in no game)
   """
   found = _scripts_manifest(doc)
   if found is None:
      return []
   path, data = found
   lay = _lay()
   first_id = None
   if removing:
      row = next((r for r in role_rows(doc) if r["name"] == name), None)
      if row is not None and row["kind"] == KIND_CUSTOM:
         first_id = row["id"]
         if storing:
            first_id = stored_position_id(doc, name)
   last_id = lay.CUSTOM_ROLE_BASE + sum(1 for e in _listed(doc) if _is_custom(e))
   out = []
   sources = data.get(SOURCES_KEY)
   for rel in sources if isinstance(sources, list) else []:
      src = path.parent / str(rel)
      try:
         refs = _script_role_refs(src.read_text(encoding="utf-8"), src.name)
      except Exception:   # OSError, the tokenizer's ScriptError: the script compiler reports it
         continue
      for line, statement, role in refs:
         number = _script_number(role)
         by_id = first_id is not None and number is not None and first_id <= number < last_id
         if role == name:
            out.append(f"scripts: {rel} line {line} ({statement} {name})")
         elif by_id:
            out.append(f"scripts: {rel} line {line} ({statement} role ID {role}: a custom role's ID moves)")
   given = data.get(PLACEHOLDERS_KEY)
   for key, binding in (given.items() if isinstance(given, dict) else []):
      if isinstance(binding, dict) and binding.get(PLACEHOLDER_RECORD_KEY) == name:
         out.append(f"scripts: placeholder {{{key}}} ({PLACEHOLDER_RECORD_KEY} {name})")
   return out


# -- the engine's layout -----------------------------------------------------------------------------------------------

def _compile_value(value: Any, stats_n: int) -> tuple[JsonDict | None, str | None]:
   """!Compiles a monster_layout value with the engine's compile_layout() (any size; the largest party any
   platform holds).
   @param value    the monster_layout value
   @param stats_n  stats of the manifest
   @return (compile_layout() result or None, the compiler's message or None)
   """
   lay = _lay()
   biggest_party = max(limits["max_party_size"] for limits in engine.tool("build_settings").PLATFORM_LIMITS.values())
   try:
      return lay.compile_layout(copy.deepcopy(value), WHERE, UNBOUNDED_RECORD_BYTES, stats_n, biggest_party), None
   except Exception as e:   # the compiler's ManifestErrors, plus type errors in odd data
      return None, str(e)


def compile_record(doc: Document) -> tuple[JsonDict | None, str | None]:
   """!The layout as the engine compiles it.
   @param doc  battle Document
   @return (compile_layout() result or None, error or None)
   """
   return _compile_value(layout_value(doc), stat_count(doc))


## Saved files' hashes: {path: ((mtime_ns, size), hash or None)}.
_saved_cache: dict[Path, tuple[tuple[int, int], int | None]] = {}


def saved_hash(doc: Document) -> int | None:
   """!The layout hash of the structure manifest as last saved (the file on disk: it holds the layout and the stats).
   @param doc  a manifest Document of the battle
   @return the hash, or None when there is no file or its layout does not compile
   """
   path = battle.structure_doc(doc).path
   if path is None or not Path(path).is_file():
      return None
   path = Path(path).resolve()
   st = path.stat()
   stamp = (st.st_mtime_ns, st.st_size)
   cached = _saved_cache.get(path)
   if cached is not None and cached[0] == stamp:
      return cached[1]
   try:
      data = manifest_io.load(path)
   except (OSError, ValueError):
      data = None
   value = None
   if isinstance(data, dict):
      names = data.get("stats")
      stats_n = len([s for s in names if isinstance(s, dict)]) if isinstance(names, list) else 0
      compiled, _error = _compile_value(data.get(LAYOUT_KEY), stats_n)
      value = compiled["hash"] if compiled is not None else None
   _saved_cache[path] = (stamp, value)
   return value


def role_max(doc: Document | None, name: str) -> int:
   """!The highest value an element of a role holds: 2^width - 1 with the layout's width (the engine's
   layout.role_max_value() of the compiled layout, the limit the battle compiler checks values against).
   @param doc   battle Document, or None for the engine registry's width (new battle data)
   @param name  an engine role, or a custom role of the layout
   @return the highest value
   """
   lay = _lay()
   compiled = compile_record(doc)[0] if doc is not None else None
   if compiled is not None:
      return lay.role_max_value(compiled, name)
   # The layout does not compile: the width it writes for the role, else the registry's.
   width = next((r["width"] for r in role_rows(doc) if r["name"] == name), None) if doc is not None else None
   if not _is_int(width):
      width = _layout().ROLE_SHAPES[name][0] if name in _layout().ROLE_SHAPES else _layout().MAX_ROLE_BITS
   return (1 << width) - 1


def stat_input_roles() -> dict[str, str]:
   """!The per-stat role each stat formula input reads (the engine's battle_compiler STAT_INPUT_ROLES,
   battlec/rules.py: gene -> stat_genes, training -> stat_training, awaken -> stat_awaken).
   @return {input: role}
   """
   return dict(engine.tool("battle_compiler").STAT_INPUT_ROLES)


def has_stat_input(doc: Document | None, key: str) -> bool:
   """!Whether a creature of this layout has a per-stat input (its role is in the layout; without it the stat
   formulas read 0: the damage calculator hides its spin).
   @param doc  battle Document, or None for the engine's default roles (genes only)
   @param key  a stat_input_roles() input
   @return True when the layout holds the role
   """
   return key in stat_inputs(doc)


def gene_max(doc: Document | None) -> int:
   """!The highest gene value of a stat (the layout's stat_genes width).
   @param doc  battle Document, or None for the engine's default width
   @return the highest value
   """
   return role_max(doc, GENES_ROLE)


def training_max(doc: Document | None) -> int:
   """!The highest training value of a stat (the layout's stat_training width).
   @param doc  battle Document, or None for the engine's default width
   @return the highest value
   """
   return role_max(doc, TRAINING_ROLE)


def awaken_max(doc: Document | None) -> int:
   """!The highest awakening value of a stat (the layout's stat_awaken width).
   @param doc  battle Document, or None for the engine's default width
   @return the highest value
   """
   return role_max(doc, AWAKEN_ROLE)


def stat_inputs(doc: Document | None) -> dict[str, int]:
   """!The per-stat inputs of the stat formulas a creature of this layout has (stat_input_roles() whose role the
   layout holds; a record without one passes 0) and the highest value of each (its role's width).
   @param doc  battle Document, or None for a layout of the engine's default roles (genes only)
   @return {input: highest value}, in stat_input_roles() order
   """
   held = role_names(doc) if doc is not None else [GENES_ROLE]
   return {k: role_max(doc, role) for k, role in stat_input_roles().items() if role in held}


def check_stat_inputs(doc: Document | None, values: dict[str, Any]) -> None:
   """!Refuses per-stat input values the layout's roles cannot hold (core.battle.BattleProject.stats(), the CLI's
   stats and damage commands, the damage calculator): each value within its role's width, the range the battle
   compiler gives the stat formulas' inputs (check_formula_ranges(): role_max_value() whether or not the layout
   holds the role; a record without it passes 0).
   @param doc     battle Document, or None
   @param values  {input ("gene", "training", "awaken"): one value per stat, or None}
   @return None
   @throws DocumentError for a value out of range
   """
   roles = stat_input_roles()
   for key, given in values.items():
      if given is None:
         continue
      role = roles[key]
      most = role_max(doc, role)
      for v in given:
         if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= most:
            raise DocumentError(f"{key}: 0 to {most} (the record layout's {role} width), got {v!r}")


def hash_text(value: int | None) -> str:
   """!A layout hash as shown.
   @param value  the hash, or None
   @return e.g. "0x1234ABCD", or "?"
   """
   return "?" if value is None else f"0x{value:08X}"


def layout_report(doc: Document, targets: list[str] | None = None) -> LayoutReport:
   """!The record as the engine lays it out, against each target.
   @param doc      battle Document
   @param targets  platforms, or None for the default targets
   @return {"bytes", "bits", "hash" (None when it does not compile), "error", "party_size", "move_slots",
           "unstored": [unstored custom role names: no bits, not hashed], "budgets": [(platform, bytes, most)],
           "problems": [text], "saved_hash", "hash_changed"}
   """
   targets = list(targets or stat_model.DEFAULT_TARGETS)
   compiled, error = compile_record(doc)
   size = compiled["bytes"] if compiled is not None else None
   out: LayoutReport = {"bytes": size, "bits": compiled["bits"] if compiled is not None else None,
                        "hash": compiled["hash"] if compiled is not None else None, "error": error,
                        "party_size": party_size(doc), "move_slots": move_slots(doc),
                        "unstored": unstored_roles(doc), "budgets": [], "problems": []}
   for t in targets:
      limits = _limits(t)
      if size is not None:
         out["budgets"].append((t, size, limits["max_record_bytes"]))
         if size > limits["max_record_bytes"]:
            out["problems"].append(f"{t}: the record needs {size} bytes, the engine stores at most "
                                   f"{limits['max_record_bytes']}")
      if out["party_size"] > limits["max_party_size"]:
         out["problems"].append(f"{t}: a party of {out['party_size']}, the engine holds at most "
                                f"{limits['max_party_size']}")
   out["saved_hash"] = saved_hash(doc)
   out["hash_changed"] = out["hash"] is not None and out["saved_hash"] is not None and \
      out["hash"] != out["saved_hash"]
   return out


def budget_text(platform: str, used: int, most: int) -> str:
   """!A record budget as shown ("61/100 B gba"; the panel shows the platform in capitals).
   @param platform  platform name
   @param used      record bytes
   @param most      the platform's limit
   @return text
   """
   return f"{used}/{most} B {platform}"


def role_line(row: RoleRow) -> str:
   """!A role as the CLI's `role list` prints it.
   @param row  role_rows() row
   @return text
   """
   rid = "?" if row["id"] is None else f"0x{row['id']:02X}"
   shape = f"{row['width']} bit(s) x {row['count']}" if row["bits"] is not None else "bad shape"
   parts = [f"{row['index']} {row['name']} [{row['kind']} {rid}] {shape}"]
   if row["count_rule"] is not None:
      parts.append(f"({row['count_rule']})")
   if row["bits"] is not None:
      parts.append(f"= {row['bits']} bits")
   if row["kind"] == KIND_CUSTOM:
      parts.append(f"default {row['default']}")
   if not row["stored"]:
      parts.append("unstored (computed on read)")
   if row["required"]:
      parts.append("required")
   parts.append("transfer " + transfer_text(row))
   return " ".join(parts)


def transfer_text(row: RoleRow, values: bool = True) -> str:
   """!A role's transfer keys as shown.
   @param row     role_rows() row
   @param values  with the 32-bit keys of custom roles ("role:gender 0x1A2B3C4D")
   @return text
   """
   keys = row["transfer"]
   if row.get("stored") is False:
      return TRANSFER_UNSTORED
   if keys is None:
      return TRANSFER_PENDING
   if values and row["kind"] == KIND_CUSTOM and row["transfer_values"]:
      return ", ".join(f"{k} {hash_text(v)}" for k, v in zip(keys, row["transfer_values"]))
   return ", ".join(keys) or "-"


def layout_lines(doc: Document, targets: list[str] | None = None) -> list[str]:
   """!The record as the CLI's `layout` prints it: size and hash, party size and move slots, each target's
   budget, problems and the saved-hash warning.
   @param doc      battle Document
   @param targets  platforms, or None for the default targets
   @return lines
   """
   r = layout_report(doc, targets)
   lines = []
   if r["error"]:
      lines.append(f"layout does not compile: {r['error']}")
   else:
      lines.append(f"record: {r['bytes']} bytes ({r['bits']} bits used), hash {hash_text(r['hash'])}")
   if r["unstored"]:
      lines.append(f"unstored (computed on read: no bits, not in the hash): {', '.join(r['unstored'])}")
   lines.append(f"party size {r['party_size']}, move slots {r['move_slots']}"
                + ("" if party_size_stated(doc) else " (the party size is not stated: the engine refuses that)")
                + ("" if move_slots_stated(doc) else " (the move slots are not stated: the engine refuses that)"))
   lines += [budget_text(t, used, most) for t, used, most in r["budgets"]]
   lines += r["problems"]
   if r["hash_changed"]:
      lines.append(f"warning: the layout hash differs from the saved file's ({hash_text(r['saved_hash'])}): "
                   "old saves won't load")
   return lines


# -- editing (inside battle.edit()) -----------------------------------------------------------------------------------

def _guarded(doc: Document, change: Callable[[], Any]) -> Any:
   """!Runs a change; when the layout compiled before and does not after, refuses it with the compiler's
   message (raised inside battle.edit(), which puts the manifest back).
   @param doc     battle Document
   @param change  the change
   @return what change() returned
   @throws DocumentError with the engine's message
   """
   _before, error_before = compile_record(doc)
   result = change()
   if error_before is None:
      _after, error = compile_record(doc)
      if error is not None:
         raise DocumentError(error)
   return result


def _object_form(doc: Document) -> JsonDict:
   """!The layout as the object form, stating its party size and move slots (the list form is converted, keeping
   its roles; the counts are the ones the layout means: the engine's registry counts when it gave none).
   @param doc  battle Document
   @return the live object
   """
   given = layout_value(doc)
   if not isinstance(given, dict):
      roles = given if isinstance(given, list) else []
      given = battle.data_of(doc, LAYOUT_KEY)[LAYOUT_KEY] = {PARTY_SIZE_KEY: party_size(doc),
                                                            MOVE_SLOTS_KEY: move_slots(doc), ROLES_KEY: roles}
   elif not _is_int(given.get(PARTY_SIZE_KEY)) or not _is_int(given.get(MOVE_SLOTS_KEY)):
      given[PARTY_SIZE_KEY] = party_size(doc)
      given[MOVE_SLOTS_KEY] = move_slots(doc)
      _set_order(given)
   return given


def _set_setting(doc: Document, key: str, value: int) -> None:
   """!Writes party_size or move_slots, in the object form's key order (party_size, move_slots, roles).
   @param doc    battle Document
   @param key    PARTY_SIZE_KEY or MOVE_SLOTS_KEY
   @param value  the value
   @return None
   """
   obj = _object_form(doc)
   obj[key] = value
   _set_order(obj)


def _set_order(obj: JsonDict) -> None:
   """!Puts the object form's keys in their order (party_size, move_slots, roles, then the rest).
   @param obj  the layout object
   @return None
   """
   ordered = {k: obj[k] for k in (PARTY_SIZE_KEY, MOVE_SLOTS_KEY, ROLES_KEY) if k in obj}
   ordered.update({k: v for k, v in obj.items() if k not in ordered})
   obj.clear()
   obj.update(ordered)


def _member_lists(doc: Document) -> list[tuple[str, list[Any]]]:
   """!Every party's members.
   @param doc  battle Document
   @return [(party name, members list)]
   """
   out = []
   for p in battle.entries(doc, "parties"):
      members = p.get("members")
      out.append((str(p.get("name")), members if isinstance(members, list) else []))
   return out


def set_move_slots(doc: Document, value: int) -> bool:
   """!Sets the move slots (the layout is written in the object form). Refused while a party member names more
   moves than that.
   @param doc    battle Document
   @param value  1 to max_move_slots()
   @return True when it changed
   """
   value = _int_in(value, 1, max_move_slots(), MOVE_SLOTS_KEY)
   if value == move_slots(doc) and move_slots_stated(doc):
      return False
   over = [f"{party} member {i + 1}" for party, members in _member_lists(doc) for i, m in enumerate(members)
           if isinstance(m, dict) and isinstance(m.get("moves"), list) and len(m["moves"]) > value]
   if over:
      raise DocumentError(f"{', '.join(over[:battle.REFERENCES_SHOWN])} name(s) more than {value} moves")
   _guarded(doc, lambda: _set_setting(doc, MOVE_SLOTS_KEY, value))
   return True


def set_party_size(doc: Document, value: int, targets: list[str] | None = None) -> bool:
   """!Sets the party size (the layout is written in the object form, stating it). Refused above what a target holds and
   while a party or a format's party_max is larger.
   @param doc      battle Document
   @param value    1 to max_party_size(targets)
   @param targets  platforms, or None for the default targets
   @return True when it changed
   """
   on = ", ".join(targets or stat_model.DEFAULT_TARGETS)
   value = _int_in(value, 1, max_party_size(targets), f"{PARTY_SIZE_KEY} (on {on})")
   if value == party_size(doc) and party_size_stated(doc):
      return False
   over = [party for party, members in _member_lists(doc) if len(members) > value]
   over += [f"format {f.get('name')} (party_max)" for f in battle.entries(doc, "formats")
            if _is_int(f.get("party_max")) and f["party_max"] > value]
   if over:
      raise DocumentError(f"{', '.join(over[:battle.REFERENCES_SHOWN])}: larger than a party of {value}")
   _guarded(doc, lambda: _set_setting(doc, PARTY_SIZE_KEY, value))
   return True


def _check_new_custom(doc: Document, name: Any, current: str | None = None) -> str:
   """!A custom role name the engine takes and the layout does not hold.
   @param doc      battle Document
   @param name     wanted name
   @param current  the role being renamed (its own name is fine), or None
   @return the name (stripped)
   @throws DocumentError when it is not one
   """
   lay = _lay()
   name = name.strip() if isinstance(name, str) else name
   if not isinstance(name, str) or not _layout().CUSTOM_NAME.match(name):
      raise DocumentError(f"a custom role's name is a lower-case identifier (got {name!r})")
   if name in lay.ROLE_NAMES and name not in lay.RETIRED_ROLES:
      raise DocumentError(f"{name!r} is an engine role (add it as one)")
   if name != current and name in role_names(doc):
      raise DocumentError(f"the record already holds a role {name!r}")
   return name


def _insert(doc: Document, entry: Any, index: int | None) -> int:
   """!Inserts an entry.
   @param doc    battle Document
   @param entry  the entry
   @param index  position, or None for the end
   @return its index
   """
   lst = _entries(doc)
   at = len(lst) if index is None else max(0, min(len(lst), int(index)))
   lst.insert(at, entry)
   return at


def add_engine_role(doc: Document, name: str, index: int | None = None, width: int | None = None,
                    count: int | None = None) -> int:
   """!Adds an engine role to the record.
   @param doc    battle Document
   @param name   one of engine_roles() the layout does not hold
   @param index  position, or None for the end
   @param width  chosen width (roles in ROLE_MAX_WIDTHS), or None for the registry's
   @param count  chosen count ("chosen" roles), or None for the registry's
   @return its index
   """
   lay = _lay()
   if name in lay.RETIRED_ROLES:
      raise DocumentError(f"{name!r} is a custom role now (add it as a custom role)")
   if name not in lay.ROLE_NAMES:
      raise DocumentError(f"unknown engine role {name!r} (engine roles: {', '.join(engine_roles())})")
   if name in role_names(doc):
      raise DocumentError(f"the record already holds {name!r}")
   at = _guarded(doc, lambda: _insert(doc, name, index))
   for key, value in ((WIDTH_KEY, width), (COUNT_KEY, count)):
      if value is not None:
         set_role(doc, name, key, value)
   return at


def add_custom_role(doc: Document, name: str, width: int, count: int | None = None, default: int | None = None,
                    index: int | None = None) -> int:
   """!Adds a custom role (a field the engine stores and scripts read and write).
   @param doc      battle Document
   @param name     lower-case identifier, not an engine role's
   @param width    bits per element (1 to battlec.layout.MAX_ROLE_BITS)
   @param count    elements (1 to MAX_CUSTOM_COUNT), or None for 1
   @param default  initial value (fits the width), or None for 0
   @param index    position, or None for the end
   @return its index
   """
   lay = _lay()
   name = _check_new_custom(doc, name)
   if sum(1 for e in _listed(doc) if _is_custom(e)) >= lay.MAX_CUSTOM_ROLES:
      raise DocumentError(f"at most {lay.MAX_CUSTOM_ROLES} custom roles")
   width = _int_in(width, 1, _layout().MAX_ROLE_BITS, WIDTH_KEY)
   entry: JsonDict = {CUSTOM_KEY: name, WIDTH_KEY: width}
   if count is not None:
      entry[COUNT_KEY] = _int_in(count, 1, lay.MAX_CUSTOM_COUNT, COUNT_KEY)
   if default is not None:
      entry[DEFAULT_KEY] = _int_in(default, 0, (1 << width) - 1, DEFAULT_KEY)
   return _guarded(doc, lambda: _insert(doc, entry, index))


def remove_role(doc: Document, name: str) -> None:
   """!Removes a role from the record (refused for the roles every battle needs, while a resource is persisted in
   it or reads its raises from it, while effect logic reads or writes it: `holder.role(NAME)`, core.logic, and
   while a field rule's expression reads it: the field effects, core.structure.field_expressions).
   @param doc   battle Document
   @param name  role name
   @return None
   """
   i = _find(doc, name)
   if name in _lay().REQUIRED_ROLES:
      raise DocumentError(f"battles need the role {name!r}")
   held = resource_model.role_resources(doc, name)
   if held:
      raise DocumentError(f"role {name!r} holds {', '.join(held)}: change that on the Resources page first")
   users = logic.per_owner(logic.references(doc, ROLE_LISTS, name))
   # The field rules' expressions (lead rules, field action requirements) read custom roles too
   from . import combination, field_expressions   # local: core.structure imports this module
   users += field_expressions.follow_role(battle.merged(doc), name, None)
   users += combination.follow_role(battle.merged(doc), name, None)   # the combination expressions' ROLE.R
   from . import nursery   # local: it imports this module
   users += nursery.follow_role(battle.merged(doc), name, None)   # the egg role and the hatch counter
   if users:
      raise DocumentError(f"role {name!r} is still used by: {', '.join(users[:battle.REFERENCES_SHOWN])}")
   custom = _is_custom(_listed(doc)[i])
   # the generation list follows: refused while a derived expression reads it, a custom role's entries dropped
   progression.drop_role(doc, name, custom)
   _guarded(doc, lambda: _entries(doc).pop(i))
   _drop_transfer_role(doc, name)


def move_role_to(doc: Document, name: str, index: int) -> bool:
   """!Moves a role to a position (its bit offset; a custom role's ID follows its place among the custom roles).
   @param doc    battle Document
   @param name   role name
   @param index  new position (clamped)
   @return True when it moved
   """
   lst = _entries(doc)
   i = _find(doc, name)
   j = max(0, min(len(lst) - 1, int(index)))
   if i == j:
      return False

   def move() -> None:
      """!Takes the entry out and puts it back at its new place.
      @return None
      """
      lst.insert(j, lst.pop(i))

   _guarded(doc, move)
   return True


def move_role(doc: Document, name: str, delta: int) -> bool:
   """!Moves a role up or down the record.
   @param doc    battle Document
   @param name   role name
   @param delta  -1 up, +1 down
   @return True when it moved
   """
   i = _find(doc, name)
   if not 0 <= i + delta < len(_listed(doc)):
      return False
   return move_role_to(doc, name, i + delta)


def _custom_dict(doc: Document, i: int) -> JsonDict:
   """!A custom role's entry as a {"custom"} object (a bare retired name is written out with its old shape).
   @param doc  battle Document
   @param i    its index
   @return the live dict
   """
   lst = _entries(doc)
   e = lst[i]
   if isinstance(e, str):
      width, count = _layout().ROLE_SHAPES[e]
      e = {CUSTOM_KEY: e, WIDTH_KEY: width}
      if count != 1:
         e[COUNT_KEY] = count
      lst[i] = e
   return e


def rename_role(doc: Document, old: str, new: str) -> bool:
   """!Renames a custom role, the resources persisted in it or reading their raises from it, the field rules'
   expressions reading it (core.structure.field_expressions) and the effect logic naming it (core.logic; engine
   roles keep their names; the hash folds a custom role's name, so saves made before
   no longer load).
   @param doc  battle Document
   @param old  current name
   @param new  new name
   @return True when renamed
   """
   i = _find(doc, old)
   if not _is_custom(_listed(doc)[i]):
      raise DocumentError(f"{old!r} is an engine role: its name is fixed")
   new = _check_new_custom(doc, new, old)
   if new == old:
      return False

   def rename() -> None:
      """!Writes the new name.
      @return None
      """
      _custom_dict(doc, i)[CUSTOM_KEY] = new
      resource_model.rename_role(doc, old, new)   # the resources' persist / raises roles follow
      # The recruit section's item role and the transformation's form role name custom roles too
      from . import combination, field_expressions, recruit, transformation   # local: they import this module
      recruit.follow_role_rename(doc, old, new)
      transformation.follow_role_rename(doc, old, new)
      field_expressions.follow_role(battle.merged(doc), old, new)   # lead rules, field action requirements
      combination.follow_role(battle.merged(doc), old, new)   # the combination expressions' ROLE.R
      from . import nursery   # local: it imports this module
      nursery.follow_role(battle.merged(doc), old, new)   # the egg role and the hatch counter

   before, _error = compile_record(doc)
   _guarded(doc, rename)
   progression.rename_role(doc, old, new, before)   # generation entries and derived expressions follow
   logic.references(doc, ROLE_LISTS, old, new, "Rename role")
   return True


def _set_engine(doc: Document, i: int, name: str, key: str, value: Any) -> None:
   """!Changes an engine role's width or count (None: the registry's).
   @param doc    battle Document
   @param i      its index
   @param name   role name
   @param key    WIDTH_KEY or COUNT_KEY
   @param value  the value, or None
   @return None
   """
   lay = _lay()
   reg_width, _reg_count = _layout().ROLE_SHAPES[name]
   if key == DEFAULT_KEY:
      raise DocumentError(f"{name!r} is an engine role: only custom roles have a default here")
   if key == WIDTH_KEY and value is not None:
      if name not in lay.ROLE_MAX_WIDTHS:
         raise DocumentError(f"the width of role {name!r} is fixed ({reg_width} bits)")
      value = _int_in(value, 1, lay.ROLE_MAX_WIDTHS[name], f"{name} width")
   if key == COUNT_KEY and value is not None:
      if name not in lay.ROLE_MAX_COUNTS:
         rule = next(r for role, _w, _n, r in lay.ROLES if role == name)
         by = MOVE_SLOTS_KEY if rule == COUNT_RULE_MOVE else "the stats" if rule == COUNT_RULE_STAT else "1"
         raise DocumentError(f"the count of role {name!r} is fixed by the layout ({by})")
      value = _int_in(value, 1, lay.ROLE_MAX_COUNTS[name], f"{name} count")
   lst = _entries(doc)
   e = lst[i] if isinstance(lst[i], dict) else {ROLE_KEY: name}
   if value is None:
      e.pop(key, None)
   else:
      e[key] = value
   # An entry that chooses nothing is written as the bare name.
   lst[i] = name if set(e) == {ROLE_KEY} else e


def _set_custom(doc: Document, i: int, key: str, value: Any) -> None:
   """!Changes a custom role's width, count or default (None: count 1, default 0; the width is required).
   @param doc    battle Document
   @param i      its index
   @param key    one of ROLE_PROPERTIES
   @param value  the value, or None
   @return None
   """
   lay = _lay()
   e = _custom_dict(doc, i)
   width = value if key == WIDTH_KEY else e.get(WIDTH_KEY)
   if key == WIDTH_KEY:
      if value is None:
         raise DocumentError(f"a custom role needs a width (1-{_layout().MAX_ROLE_BITS} bits)")
      width = _int_in(value, 1, _layout().MAX_ROLE_BITS, WIDTH_KEY)
      default = e.get(DEFAULT_KEY, 0)
      if _is_int(default) and default > (1 << width) - 1:
         raise DocumentError(f"the default {default} does not fit in {width} bits")
   elif key == COUNT_KEY and value is not None:
      value = _int_in(value, 1, lay.MAX_CUSTOM_COUNT, COUNT_KEY)
   elif key == DEFAULT_KEY and value is not None:
      most = (1 << width) - 1 if _is_int(width) else (1 << _layout().MAX_ROLE_BITS) - 1
      value = _int_in(value, 0, most, DEFAULT_KEY)
   if value is None:
      e.pop(key, None)
   else:
      e[key] = value


def set_role(doc: Document, name: str, key: str, value: Any) -> bool:
   """!Changes one property of a role: an engine role's width (ROLE_MAX_WIDTHS roles) or count ("chosen"
   roles), a custom role's width, count or default. None puts the default back (the registry's shape; count 1,
   default 0).
   @param doc    battle Document
   @param name   role name
   @param key    one of ROLE_PROPERTIES
   @param value  int, or None
   @return True when it changed
   """
   if key not in ROLE_PROPERTIES:
      raise DocumentError(f"unknown role property {key!r} (properties: {', '.join(ROLE_PROPERTIES)}; the name: "
                          "rename)")
   i = _find(doc, name)
   before = copy.deepcopy(_listed(doc)[i])
   if _is_custom(_listed(doc)[i]):
      _guarded(doc, lambda: _set_custom(doc, i, key, value))
   elif name in _layout().ROLE_SHAPES:
      _guarded(doc, lambda: _set_engine(doc, i, name, key, value))
   else:
      raise DocumentError(f"unknown role {name!r}")
   return _listed(doc)[i] != before


def stored_problem(doc: Document, name: str) -> str | None:
   """!Why a custom role cannot be unstored (computed on read, it needs exactly one derived or constant
   generation entry, the engine's UNSTORED_KINDS; check_unstored() refuses anything else).
   @param doc   battle Document
   @param name  role name
   @return the reason, or None when it may be unstored
   """
   kinds = progression.unstored_kinds()
   ways = [progression.way_of(progression.entries_of(doc)[k]) for k in progression.fillers(doc, name)]
   if len(ways) == 1 and ways[0] in kinds:
      return None
   has = ", ".join(str(w) for w in ways) or "none"
   return (f"role {name!r} is computed on read when unstored: give it exactly one {' or '.join(kinds)} "
           f"generation entry first (Progression page; it has {has})")


def set_stored(doc: Document, name: str, stored: bool) -> bool:
   """!Whether the record holds a custom role (the record fields "stored": false: computed on read from its derived or
   constant generation entry; no record bits, out of the hash and the transfer, its ID after the stored custom roles').
   Turning it off is refused unless the role has exactly one derived or constant entry (stored_problem()); field
   scripts then read it as 0 (the editors ask, the CLI wants --force: role_users()).
   @param doc     battle Document
   @param name    a custom role
   @param stored  True: the record holds it (the key is dropped); False: computed on read
   @return True when it changed
   @throws DocumentError for an engine role, a role without the entry, or data the engine then refuses
   """
   i = _find(doc, name)
   if not _is_custom(_listed(doc)[i]):
      raise DocumentError(f"{name!r} is an engine role: the record always holds it")
   if is_stored(_listed(doc)[i]) == bool(stored):
      return False
   if not stored:
      problem = stored_problem(doc, name)
      if problem is not None:
         raise DocumentError(problem)

   def change() -> None:
      """!Writes the flag (a stored role leaves it out: the engine's default).
      @return None
      """
      e = _custom_dict(doc, i)
      if stored:
         e.pop(STORED_KEY, None)
      else:
         e[STORED_KEY] = False

   # the layout and the generation list must keep compiling (the engine's check_unstored() is the authority)
   generation_before = progression.compile_progress(doc)[progression.GENERATION_KEY]
   _guarded(doc, change)
   if generation_before is None:
      error = progression.compile_progress(doc)[progression.GENERATION_KEY]
      if error is not None:
         raise DocumentError(error)
   return True


# -- transfer defaults (monster_layout.transfer_defaults) ---------------------------------------------------------

## The object form's transfer defaults: {stat name: value, or {per-stat role: value}}.
TRANSFER_DEFAULTS_KEY = "transfer_defaults"
## Value a transfer gives a stat the sending game lacks when the layout names none (battlec/transfer.py).
TRANSFER_DEFAULT_VALUE = 0


def per_stat_roles(doc: Document) -> list[str]:
   """!The per-stat engine roles the layout holds (a transfer default gives each a value).
   @param doc  battle Document
   @return names in record order
   """
   return [r["name"] for r in role_rows(doc) if r["kind"] == KIND_ENGINE and r["count_rule"] == COUNT_RULE_STAT]


def _defaults_given(doc: Document) -> dict[str, Any]:
   """!The manifest's transfer defaults for reading.
   @param doc  battle Document
   @return the dict ({} without one)
   """
   given = layout_value(doc)
   value = given.get(TRANSFER_DEFAULTS_KEY) if isinstance(given, dict) else None
   return value if isinstance(value, dict) else {}


def transfer_defaults(doc: Document) -> list[JsonDict]:
   """!What a record transfer gives each stat a sending game does not have, per held per-stat role.
   @param doc  battle Document
   @return per stat: stat, values {role: value}, given (True when the layout names the stat), uniform (True
           when one value covers every role: the manifest's integer form)
   """
   given = _defaults_given(doc)
   roles = per_stat_roles(doc)
   out = []
   for st in stat_model.stat_list(doc):
      name = st["name"]
      v = given.get(name)
      if isinstance(v, dict):
         values = {r: v.get(r, TRANSFER_DEFAULT_VALUE) for r in roles}
      else:
         values = {r: v if _is_int(v) else TRANSFER_DEFAULT_VALUE for r in roles}
      out.append({"stat": name, "values": values, "given": name in given, "uniform": not isinstance(v, dict)})
   return out


def set_transfer_default(doc: Document, stat: str, value: int | None, role: str | None = None) -> None:
   """!Sets what a transfer gives a stat the sending game lacks (the layout is written in the object form).
   @param doc    battle Document
   @param stat   a stat of the manifest
   @param value  the value (within the role's width), or None to drop it (TRANSFER_DEFAULT_VALUE)
   @param role   one per-stat role, or None for every one (the integer form)
   @return None
   """
   if stat not in [st["name"] for st in stat_model.stat_list(doc)]:
      raise DocumentError(f"no stat {stat!r}")
   roles = per_stat_roles(doc)
   if role is not None and role not in roles:
      raise DocumentError(f"{role!r} is no per-stat role of the layout ({', '.join(roles) or 'none'})")
   if value is not None:
      for r in [role] if role is not None else roles:
         _int_in(value, 0, role_max(doc, r), f"{TRANSFER_DEFAULTS_KEY}.{stat}.{r}")

   def change() -> None:
      """!Writes the default (dropping empty objects).
      @return None
      """
      obj = _object_form(doc)
      defaults = obj.get(TRANSFER_DEFAULTS_KEY)
      if not isinstance(defaults, dict):
         defaults = obj[TRANSFER_DEFAULTS_KEY] = {}
      if role is None:
         if value is None:
            defaults.pop(stat, None)
         else:
            defaults[stat] = value
      else:
         current = defaults.get(stat)
         per = dict(current) if isinstance(current, dict) else \
            ({r: current for r in roles} if _is_int(current) else {})
         if value is None:
            per.pop(role, None)
         else:
            per[role] = value
         if per:
            defaults[stat] = per
         else:
            defaults.pop(stat, None)
      if not defaults:
         obj.pop(TRANSFER_DEFAULTS_KEY)

   _guarded(doc, change)


def rename_transfer_stat(doc: Document, old: str, new: str) -> bool:
   """!Follows a stat rename in the transfer defaults (core.structure.stats calls it).
   @param doc  battle Document
   @param old  old stat name
   @param new  new stat name
   @return True when the defaults named it
   """
   defaults = _defaults_given(doc)
   if old not in defaults:
      return False
   defaults[new] = defaults.pop(old)
   return True


def drop_transfer_stat(doc: Document, name: str) -> bool:
   """!Follows a stat removal in the transfer defaults.
   @param doc   battle Document
   @param name  the stat
   @return True when the defaults named it
   """
   defaults = _defaults_given(doc)
   if name not in defaults:
      return False
   del defaults[name]
   if not defaults:
      layout_value(doc).pop(TRANSFER_DEFAULTS_KEY)
   return True


def _drop_transfer_role(doc: Document, role: str) -> None:
   """!Follows a role removal in the transfer defaults' per-role objects.
   @param doc   battle Document
   @param role  the removed role
   @return None
   """
   defaults = _defaults_given(doc)
   for stat in list(defaults):
      v = defaults[stat]
      if isinstance(v, dict) and role in v:
         del v[role]
         if not v:
            del defaults[stat]
   if not defaults and isinstance(layout_value(doc), dict):
      layout_value(doc).pop(TRANSFER_DEFAULTS_KEY, None)


def transfer_lines(doc: Document) -> list[str]:
   """!The transfer defaults as text lines.
   @param doc  battle Document
   @return one line per stat
   """
   out = []
   for row in transfer_defaults(doc):
      values = ", ".join(f"{r} {v}" for r, v in row["values"].items()) or "no per-stat roles"
      out.append(f"{row['stat']}: {values}" + ("" if row["given"] else " (default)"))
   return out
