"""!The field actions of battle data (engine F2, D-27 section 3): the structure manifest's "field_actions".

    structure.json  "field_actions": [{"name": "wade", "label": "Wade", "requires": "knows.tide_slam",
                                       "target": {"behavior": "water"}, "ask": true,
                                       "prompt": "The water is calm.\\nWade across?", "script": "field_wade"}]

A field action is a move used outside battle: crossing water, clearing a bush, lighting a dark cave, flying. Its
requirement is the growth `when` language over a party member (roles, stat.NAME, species.NAME) plus `knows.MOVE`,
`passive` (`passive == passive.NAME`) and the game state `flag.NAME` / `var.NAME` (the game's script flags and
variables, e.g. a badge); the engine compiles it as one more growth rule, and the first member in party order it
holds for uses the action. Its target is a world behavior faced (water), an object kind faced (a bush), a map tag
(a menu action on maps with that tag) or none (a menu action anywhere). An asking action shows its prompt as a
yes / no question first; then its script runs (the member's party slot in the implicit variable
field_action_member). The names, choices and checks are the engine's (battle_compiler re-exports battlec/field.py:
FIELD_ACTION_TARGETS, MAX_FIELD_ACTIONS, FIELD_ACTION_MAX_PROMPT, FIELD_ACTION_DEFAULT_PROMPT,
FIELD_ACTION_MEMBER_VAR, FIELD_ACTION_KNOWS, FIELD_ACTION_PASSIVE, FIELD_ACTION_GAME_REFS,
compile_field_action_records(), field_action_move_word(), field_action_passive_word(), field_action_ask_script(),
action_member()); the target and script choices are the game's world and scripts manifest as the engine's map and
script compilers read them (the game's reference/project.json "maps" and "scripts").

Each editing helper is one change: call it inside one edit() of either manifest. A rename follows the game's
`.cscript` sources naming the action (`field_action available NAME`, core.scripts.rename_statement_name(): saved at
once, undone with the edit); an edit that stops data that compiled from compiling is refused with the engine's
message. check_requirement() is the page's live check (the whole battle data compiled with the expression).
"""
from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

from .. import battle, engine, logic
from ..document import Document, DocumentError

if TYPE_CHECKING:
   from ..battle import BattleProject

## A parsed JSON object.
JsonDict = dict[str, Any]

## The structure manifest's list of field actions.
ACTIONS_KEY = "field_actions"
## An action's name.
NAME_KEY = "name"
## What menus show.
LABEL_KEY = "label"
## The requirement expression.
REQUIRES_KEY = "requires"
## The target ({KIND: NAME}).
TARGET_KEY = "target"
## Whether it asks first.
ASK_KEY = "ask"
## The question.
PROMPT_KEY = "prompt"
## The script it runs.
SCRIPT_KEY = "script"
## Whether an action asks when it states nothing (battlec/field.py compile_field_action_records()).
DEFAULT_ASK = True
## The target kind of a menu action anywhere (the engine's first target kind).
MENU_TARGET = "none"
## Location the compiler's messages name.
WHERE = "structure"
## The project.json key of the game's world (core.project game_files()).
WORLD_FILE_KEY = "maps"
## Items of a learnset entry ([level, move]).
LEARNSET_PAIR = 2
## Each target kind's list in the world (load_world_field()).
TARGET_LISTS = {"behavior": "behaviors", "object": "object_kinds", "tag": "map_tags"}


class ActionRow(TypedDict):
   """!One field action as the page and the CLI show it."""
   ## Position in the list (its FIELD_ACTION_<NAME> id).
   index: int
   ## Its name.
   name: str
   ## What menus show (the name when it states none).
   label: str
   ## The requirement ("" for none: any member).
   requires: str
   ## none, behavior, object or tag.
   target: str
   ## The target's name ("" for none).
   target_name: str
   ## Whether it asks first.
   ask: bool
   ## The question it shows (its own or the engine's default).
   prompt: str
   ## The script it runs.
   script: str
   ## The implicit wrapper script of an asking action ("" when it does not ask).
   ask_script: str


def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


def _sc() -> Any:
   """!The engine's script compiler.
   @return module
   """
   return engine.tool("script_compiler")


def target_kinds() -> list[str]:
   """!The target kinds (the engine's FIELD_ACTION_TARGETS, in capsule::script::ActionTarget order).
   @return names
   """
   return list(_bc().FIELD_ACTION_TARGETS)


def max_actions() -> int:
   """!The most field actions (the engine's MAX_FIELD_ACTIONS).
   @return it
   """
   return int(_bc().MAX_FIELD_ACTIONS)


def max_label() -> int:
   """!The longest label (the engine's, shared with the field effects).
   @return letters
   """
   return int(_bc().FIELD_EFFECT_MAX_LABEL)


def max_prompt() -> int:
   """!The longest prompt (the engine's FIELD_ACTION_MAX_PROMPT).
   @return letters
   """
   return int(_bc().FIELD_ACTION_MAX_PROMPT)


def member_var() -> str:
   """!The implicit variable an action's script reads its member from (the engine's FIELD_ACTION_MEMBER_VAR).
   @return the name
   """
   return str(_bc().FIELD_ACTION_MEMBER_VAR)


def default_prompt(label: str) -> str:
   """!The question an asking action without its own shows (the engine's FIELD_ACTION_DEFAULT_PROMPT).
   @param label  the action's label
   @return the text
   """
   return str(_bc().FIELD_ACTION_DEFAULT_PROMPT).format(label=label)


def actions(doc: Document | None) -> list[JsonDict]:
   """!The records in order (live).
   @param doc  any manifest Document of the battle, or None
   @return record dicts (entries that are not objects with a name are left out)
   """
   if doc is None:
      return []
   given = battle.data_of(doc, ACTIONS_KEY).get(ACTIONS_KEY)
   return [a for a in given if isinstance(a, dict) and isinstance(a.get(NAME_KEY), str)] \
      if isinstance(given, list) else []


def action_names(doc: Document | None) -> list[str]:
   """!The record names in order.
   @param doc  any manifest Document of the battle, or None
   @return names
   """
   return [a[NAME_KEY] for a in actions(doc)]


def _target(a: JsonDict) -> tuple[str, str]:
   """!A record's target.
   @param a  the record
   @return (kind, name): (MENU_TARGET, "") for a menu action
   """
   t = a.get(TARGET_KEY)
   if isinstance(t, dict) and len(t) == 1:
      kind, name = next(iter(t.items()))
      return str(kind), str(name)
   return MENU_TARGET, ""


def action_rows(doc: Document) -> list[ActionRow]:
   """!The records with their defaults filled in and their implicit script names.
   @param doc  any manifest Document of the battle
   @return one row per record
   """
   bc = _bc()
   out = []
   for i, a in enumerate(actions(doc)):
      name = a[NAME_KEY]
      label = str(a.get(LABEL_KEY, name))
      ask = bool(a.get(ASK_KEY, DEFAULT_ASK))
      prompt = a.get(PROMPT_KEY)
      kind, target = _target(a)
      requires = a.get(REQUIRES_KEY)
      out.append(ActionRow(index=i, name=name, label=label, requires=requires if isinstance(requires, str) else "",
                           target=kind, target_name=target, ask=ask,
                           prompt=prompt if isinstance(prompt, str) else default_prompt(label),
                           script=str(a.get(SCRIPT_KEY, "")),
                           ask_script=bc.field_action_ask_script(name) if ask else ""))
   return out


def compile_check(doc: Document) -> tuple[list[JsonDict] | None, str | None]:
   """!Checks the records with the engine's compile_field_action_records() (the requirements need the whole
   battle: check_requirement()).
   @param doc  any manifest Document of the battle
   @return (compiled records or None, the compiler's message or None)
   """
   bc = _bc()
   try:
      given = bc.strip(copy.deepcopy(battle.data_of(doc, ACTIONS_KEY).get(ACTIONS_KEY)))
      return bc.compile_field_action_records(given, WHERE), None
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
   data = battle.data_of(doc, ACTIONS_KEY)
   if not isinstance(data.get(ACTIONS_KEY), list):
      data[ACTIONS_KEY] = []
   return data[ACTIONS_KEY]


def _action(doc: Document, name: str) -> JsonDict:
   """!One record (live).
   @param doc   any manifest Document of the battle
   @param name  record name
   @return the dict
   @throws DocumentError when there is no such record
   """
   for a in actions(doc):
      if a[NAME_KEY] == name:
         return a
   raise DocumentError(f"no field action {name!r} (field actions: {', '.join(action_names(doc)) or 'none'})")


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
      raise DocumentError("a field action needs a name")
   if name != current and name in action_names(doc):
      raise DocumentError(f"there is already a field action {name!r}")
   return name


# -- the game's world and scripts (the choice lists) ---------------------------------------------------------------

def _game_file(doc: Document, key: str) -> Path | None:
   """!One of the game's files (its reference/project.json), for the battle data a Document belongs to.
   @param doc  any manifest Document of the battle
   @param key  the project.json key (WORLD_FILE_KEY, "scripts")
   @return the file, or None outside a game or without one
   """
   from .. import codepage, project as projects   # local: core.codepage imports core.battle
   project = logic.project_of(doc)
   path = project.battle.path if project is not None else doc.path
   found = codepage.find_project(path) if path is not None else None
   if found is None:
      return None
   try:
      got = projects.game_files(codepage.open_project(found)).get(key)
   except (DocumentError, OSError, ValueError):
      return None
   return got if got is not None and Path(got).is_file() else None


def world_lists(doc: Document) -> dict[str, list[str]]:
   """!What the game's world offers as targets (the engine's script compiler reads them the same way:
   load_world_field()).
   @param doc  any manifest Document of the battle
   @return {"behavior": names, "object": names, "tag": names} (empty lists without a world)
   """
   path = _game_file(doc, WORLD_FILE_KEY)
   empty: dict[str, list[str]] = {k: [] for k in TARGET_LISTS}
   if path is None:
      return empty
   try:
      got = _sc().load_world_field(path)
   except Exception:   # an unreadable world: the map compiler reports it
      return empty
   return {kind: list(got[key]) for kind, key in TARGET_LISTS.items()}


def target_choices(doc: Document, kind: str) -> list[str]:
   """!The names a target of a kind may name: the game's world's, plus the ones the actions already name.
   @param doc   any manifest Document of the battle
   @param kind  one of target_kinds()
   @return names (none for a menu action anywhere)
   """
   if kind == MENU_TARGET:
      return []
   names = list(world_lists(doc).get(kind, []))
   for a in actions(doc):
      k, n = _target(a)
      if k == kind and n not in names:
         names.append(n)
   return names


def script_names(doc: Document) -> dict[str, list[str]]:
   """!The game's script, flag and variable names (its scripts manifest, as the engine's script compiler declares
   them).
   @param doc  any manifest Document of the battle
   @return {"script": names, "flag": names, "var": names} (empty lists without one)
   """
   path = _game_file(doc, "scripts")
   out: dict[str, list[str]] = {"script": [], "flag": [], "var": []}
   if path is None:
      return out
   try:
      comp = _sc().compile_file(path)
   except Exception:   # an unreadable manifest: the script editor reports it
      return out
   # the implicit declarations (field effects', field actions', flight points', the escape point's) are no choices
   implicit = {comp.field_effect_file, comp.field_action_file, getattr(comp, "step_effect_file", None)}
   tables = {"script": comp.scripts, "flag": comp.flags, "var": comp.vars}
   for kind in out:
      out[kind] = [n for n in comp.order.get(kind, []) if tables[kind].get(n, {}).get("file") not in implicit]
   return out


def requirement_words(doc: Document) -> list[str]:
   """!What a requirement may read: the member's inputs (the growth scope the engine compiles it in: roles,
   stat.NAME, species.NAME, knows.MOVE, passive), the passive words and the game state (flag.NAME / var.NAME of
   the game's scripts manifest).
   @param doc  any manifest Document of the battle
   @return names (sorted, the game state last)
   """
   bc = _bc()
   project = logic.project_of(doc)
   words: list[str] = []
   compiled = project.compile()[0] if project is not None else None
   if compiled is not None:
      scope = compiled["transform"]["scope"]
      words = sorted(n for n in scope.ranges if not n.startswith(tuple(f"{k}." for k in bc.FIELD_ACTION_GAME_REFS)))
      words += sorted(bc.field_action_move_word(m) for m in compiled["names"]["moves"]
                      if bc.field_action_move_word(m) not in words)
      words += sorted(bc.field_action_passive_word(p) for p in compiled["names"]["passives"])
      if bc.FIELD_ACTION_PASSIVE not in words:
         words.append(bc.FIELD_ACTION_PASSIVE)
   names = script_names(doc)
   words += [f"flag.{n}" for n in names["flag"]] + [f"var.{n}" for n in names["var"]]
   return words


def check_requirement(doc: Document, name: str, text: str) -> str | None:
   """!Whether a requirement compiles for an action (the engine's checks: it parses, every name is an input,
   the interval analysis keeps it in int32, it can hold), with the whole battle data as the Documents hold it.
   @param doc   any manifest Document of the battle
   @param name  the action
   @param text  the expression ("" for none: any member)
   @return the engine's message, or None when it compiles
   """
   project = logic.project_of(doc)
   if project is None:
      return None
   bc = _bc()
   sources = project.sources()
   structure = copy.deepcopy(project.structure.data)
   for a in structure.get(ACTIONS_KEY) or []:
      if isinstance(a, dict) and a.get(NAME_KEY) == name:
         if text.strip():
            a[REQUIRES_KEY] = text
         else:
            a.pop(REQUIRES_KEY, None)
   sources[project.structure.path] = structure
   try:
      bc.compile_battle(project.battle.path, None, sources, **project.scripts_option(bc))
   except Exception as e:   # the engine's ManifestError
      return str(e)
   # The script compiler resolves the game state the requirement reads (field_action_ref_records()): the same
   # check here, against every flag and variable the game's scripts declare (the implicit ones too).
   declared = _declared(doc)
   if declared is None:
      return None
   for kind, ref in bc.field_action_refs([{REQUIRES_KEY: text}]):
      if ref not in declared.get(kind, set()):
         return f"a requirement reads {kind}.{ref}, which the scripts do not declare"
   return None


def _declared(doc: Document) -> dict[str, set[str]] | None:
   """!Every flag and variable the game's scripts manifest declares (implicit declarations included).
   @param doc  any manifest Document of the battle
   @return {"flag": names, "var": names}, or None without a scripts manifest (or one that does not compile)
   """
   path = _game_file(doc, "scripts")
   if path is None:
      return None
   try:
      comp = _sc().compile_file(path)
   except Exception:   # an unreadable manifest: the script editor reports it
      return None
   return {"flag": set(comp.flags), "var": set(comp.vars)}


def preview(project: BattleProject, party: list[JsonDict], game: dict[str, int] | None = None) -> dict[str, int | None]:
   """!Who would use each action (the engine's Python mirror, bc.action_member()).
   @param project  the battle data
   @param party    record dicts in party order ({"species", "level", "moves": names, ...})
   @param game     "flag.NAME" / "var.NAME" -> value (absent: 0)
   @return action name -> party slot, or None
   @throws DocumentError when the battle data does not compile
   """
   compiled, error = project.compile()
   if compiled is None:
      raise DocumentError(error or "the battle data does not compile")
   bc = _bc()
   return {a["name"]: bc.action_member(compiled, party, a["name"], game)
           for a in compiled["field"]["actions"]["actions"]}


def party_records(project: BattleProject, party_name: str) -> list[JsonDict]:
   """!A party of the battle data as record dicts for preview() (members with their learnset's moves up to their
   level when they state none: the engine's default moves, near enough for a preview).
   @param project     the battle data
   @param party_name  one of the battle's parties
   @return record dicts
   @throws DocumentError for an unknown party
   """
   for p in battle.entries(project.battle, "parties"):
      if p.get("name") != party_name:
         continue
      out = []
      for m in p.get("members") or []:
         rec: JsonDict = {"species": m.get("species"), "level": int(m.get("level", 1))}
         if isinstance(m.get("moves"), list):
            rec["moves"] = [x for x in m["moves"] if isinstance(x, str)]
         else:
            sp = next((s for s in battle.entries(project.battle, "species") if s.get("name") == m.get("species")),
                      {})
            # learnset entries are [level, move] pairs
            rec["moves"] = [e[1] for e in sp.get("learnset") or []
                            if isinstance(e, list) and len(e) == LEARNSET_PAIR and int(e[0]) <= rec["level"]]
         out.append(rec)
      return out
   raise DocumentError(f"no party {party_name!r}")


# -- editing --------------------------------------------------------------------------------------------------------

def add_action(doc: Document, name: str, script: str, target: str = MENU_TARGET, target_name: str | None = None,
               at: int | None = None) -> None:
   """!Adds a record (the engine's defaults: asks, no requirement).
   @param doc          any manifest Document of the battle
   @param name         its name
   @param script       the script it runs
   @param target       one of target_kinds()
   @param target_name  the target's name (not for MENU_TARGET)
   @param at           its position (None: last)
   @return None
   """
   name = _check_name(doc, name)
   if len(actions(doc)) >= max_actions():
      raise DocumentError(f"at most {max_actions()} field actions")
   record: JsonDict = {NAME_KEY: name}
   _apply_target(record, target, target_name)
   record[SCRIPT_KEY] = _check_script(script)

   def change() -> None:
      """!Inserts it."""
      live = _live(doc)
      live.insert(len(live) if at is None else max(0, min(at, len(live))), record)
   _guarded(doc, change)


def _check_script(script: Any) -> str:
   """!A script name (the engine's script compiler checks that the game declares it).
   @param script  the name
   @return it, stripped
   @throws DocumentError when empty
   """
   script = script.strip() if isinstance(script, str) else script
   if not isinstance(script, str) or not script:
      raise DocumentError("a field action needs the script it runs")
   return script


def _apply_target(record: JsonDict, kind: str, name: str | None) -> None:
   """!Writes a target into a record (a menu action anywhere: no key).
   @param record  the record
   @param kind    one of target_kinds()
   @param name    the target's name
   @return None
   @throws DocumentError for an unknown kind or a missing name
   """
   if kind not in target_kinds():
      raise DocumentError(f"target: one of {', '.join(target_kinds())} (got {kind!r})")
   if kind == MENU_TARGET:
      record.pop(TARGET_KEY, None)
      return
   name = name.strip() if isinstance(name, str) else ""
   if not name:
      raise DocumentError(f"a {kind} target needs a name")
   record[TARGET_KEY] = {kind: name}


def remove_action(doc: Document, name: str) -> None:
   """!Removes a record.
   @param doc   any manifest Document of the battle
   @param name  record name
   @return None
   """
   _action(doc, name)
   _guarded(doc, lambda: _live(doc).remove(_action(doc, name)))


def rename_action(doc: Document, old: str, new: str, follow: bool = True) -> list[str]:
   """!Renames a record; the game's scripts naming it follow (`field_action available OLD`).
   @param doc     any manifest Document of the battle
   @param old     its name
   @param new     the new name
   @param follow  False to leave the game's scripts to follow_scripts() (C8: the CLI follows them only once the
                  renamed battle data compiled and was saved)
   @return the script places rewritten ("FILE (n)")
   """
   new = _check_name(doc, new, old)
   a = _action(doc, old)
   _guarded(doc, lambda: a.__setitem__(NAME_KEY, new))
   return follow_scripts(doc, old, new) if follow else []


def follow_scripts(doc: Document, old: str, new: str) -> list[str]:
   """!The game's scripts follow a rename (`field_action available NAME`; saved at once, undone with the edit
   group).
   @param doc  any manifest Document of the battle
   @param old  the old name
   @param new  the new name
   @return the script places rewritten ("FILE (n)")
   """
   from .. import scripts
   return scripts.follow_rename(_game_file(doc, "scripts"), _sc().FIELD_ACTION_WORD, list(_sc().FIELD_ACTION_KINDS),
                                old, new)


def _world_battle(world_path: Path | None) -> Path | None:
   """!The battle data of the game a world belongs to (its reference/project.json "battle").
   @param world_path  the world manifest, or None
   @return battle.json, or None outside a game or without battle data
   """
   from .. import codepage, project as projects   # local: core.codepage imports core.battle
   found = codepage.find_project(world_path) if world_path is not None else None
   if found is None:
      return None
   try:
      got = projects.game_files(codepage.open_project(found)).get("battle")
   except (DocumentError, OSError, ValueError):
      return None
   return got if got is not None and Path(got).is_file() else None


def _targeting(d: JsonDict, kind: str, name: str) -> list[JsonDict]:
   """!The records whose target is a world name.
   @param d     the battle data (core.battle.merged())
   @param kind  a target kind ("object", "tag")
   @param name  the world's name
   @return the live records
   """
   given = d.get(ACTIONS_KEY)
   return [a for a in given if isinstance(a, dict) and isinstance(a.get(TARGET_KEY), dict)
           and a[TARGET_KEY].get(kind) == name] if isinstance(given, list) else []


def world_target_users(world_path: Path | None, kind: str, name: str) -> list[str]:
   """!The game's field actions targeting an object kind or map tag of its world (C8: a removal in the world is
   refused while one does).
   @param world_path  the world manifest
   @param kind        "object" or "tag"
   @param name        the world's name
   @return "field action NAME" per record
   """
   battle_json = _world_battle(world_path)
   if battle_json is None:
      return []
   try:
      project = battle.BattleProject.open(battle_json)
   except (DocumentError, OSError, ValueError):
      return []
   return [f"field action {a.get(NAME_KEY)}" for a in _targeting(battle.merged(project.structure), kind, name)]


def follow_world_rename(world_path: Path | None, kind: str, old: str, new: str) -> list[str]:
   """!The game's field actions follow an object kind or map tag rename of its world (C8, F2's open item; called when
   the renamed world was saved: core.map_field.follow_saved_renames()): their targets are rewritten and the battle
   data saved.
   @param world_path  the world manifest
   @param kind        "object" or "tag"
   @param old         the old name
   @param new         the new name
   @return "field action NAME" per record rewritten
   """
   battle_json = _world_battle(world_path)
   if battle_json is None or old == new:
      return []
   try:
      project = battle.BattleProject.open(battle_json)
   except (DocumentError, OSError, ValueError):
      return []
   hits = _targeting(battle.merged(project.structure), kind, old)
   if not hits:
      return []
   with project.structure.edit("Follow the world's rename"):
      for record in _targeting(battle.merged(project.structure), kind, old):
         record[TARGET_KEY][kind] = new
   project.save_all()
   return [f"field action {r.get(NAME_KEY)}" for r in hits]


def move_action(doc: Document, name: str, delta: int) -> None:
   """!Moves a record up or down (the FIELD_ACTION_<NAME> ids follow the order).
   @param doc    any manifest Document of the battle
   @param name   record name
   @param delta  -1 up, +1 down
   @return None
   """
   names = action_names(doc)
   if name not in names:
      raise DocumentError(f"no field action {name!r}")
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
   a = _action(doc, name)

   def change() -> None:
      """!Writes it."""
      if value == default:
         a.pop(key, None)
      else:
         a[key] = value
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


def set_requires(doc: Document, name: str, text: str) -> None:
   """!Sets the requirement (empty: none, any member); refused with the engine's message when it does not compile.
   @param doc   any manifest Document of the battle
   @param name  record name
   @param text  the expression
   @return None
   """
   text = text.strip() if isinstance(text, str) else ""
   error = check_requirement(doc, name, text)
   if error is not None:
      raise DocumentError(error)
   _set_key(doc, name, REQUIRES_KEY, text or None, None)


def set_target(doc: Document, name: str, kind: str, target_name: str | None = None) -> None:
   """!Sets what the action is used on.
   @param doc          any manifest Document of the battle
   @param name         record name
   @param kind         one of target_kinds()
   @param target_name  the behavior, object kind or map tag (not for MENU_TARGET)
   @return None
   """
   a = _action(doc, name)
   probe: JsonDict = {}
   _apply_target(probe, kind, target_name)
   _guarded(doc, lambda: (a.pop(TARGET_KEY, None), a.update(probe)))


def set_ask(doc: Document, name: str, ask: bool) -> None:
   """!Sets whether the action asks first.
   @param doc   any manifest Document of the battle
   @param name  record name
   @param ask   on or off
   @return None
   """
   _set_key(doc, name, ASK_KEY, bool(ask), DEFAULT_ASK)


def set_prompt(doc: Document, name: str, prompt: str) -> None:
   """!Sets the question an asking action shows (empty: the engine's default, the key goes).
   @param doc     any manifest Document of the battle
   @param name    record name
   @param prompt  0 to max_prompt() letters ("\\n" breaks a line)
   @return None
   """
   prompt = prompt.strip() if isinstance(prompt, str) else prompt
   if not isinstance(prompt, str) or len(prompt) > max_prompt():
      raise DocumentError(f"a prompt is at most {max_prompt()} letters")
   _set_key(doc, name, PROMPT_KEY, prompt or None, None)


def set_script(doc: Document, name: str, script: str) -> None:
   """!Sets the script the action runs.
   @param doc     any manifest Document of the battle
   @param name    record name
   @param script  a script of the game's scripts manifest
   @return None
   """
   _set_key(doc, name, SCRIPT_KEY, _check_script(script), None)


def lines(doc: Document) -> list[str]:
   """!The records as text (the CLI's list).
   @param doc  any manifest Document of the battle
   @return one line per record
   """
   out = []
   for r in action_rows(doc):
      target = f"{r['target']} {r['target_name']}" if r["target_name"] else "menu (anywhere)"
      if r["target"] == "tag":
         target = f"menu on maps tagged {r['target_name']}"
      asks = f"asks {json.dumps(r['prompt'])}" if r["ask"] else "does not ask"
      out.append(f"{r['index']}: {r['name']} ({r['label']}) requires {r['requires'] or 'nothing'}; {target}; "
                 f"{asks}; runs {r['script']}")
   return out
