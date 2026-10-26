"""!The battle test bench (D-23 §3.3, Logic > Bench): `capsule.bench/1`
scenarios run through the engine's compiled bench (apps/battle_bench).

The engine's tools/bench_scenario.py is the one authority on scenarios:
their shape (validate()), the bench's build (build) and its output
(parse_output(), Result). This module adds what the studio needs around it:

- scenarios as Documents (schema capsule.bench/1), stored in the game
  folder under bench/ (bench/NAME.json; names and the "expect" transcript
  are relative paths);
- a new scenario from the battle data (format, parties of the data, seed);
- the build: the bench is configured once into the game's build folder
  (build/bench/GENERATOR, relative to the game folder; one folder per
  generator so switching does not configure again) and rebuilt
  incrementally before every run; progress is reported by phase and a
  failed build raises BenchError with the compiler's output;
- runs: synchronous functions over a cancellable Runner (the panel runs it
  in a thread; cancel() kills the build or the bench);
- results: an event list (transcript lines with the random draws made
  before each, RNG, VM and battle event records) and VM / RNG trace
  positions (owner, hook, pc, file, line, column) for the Effects page;
- renames: a rename of an entry a scenario names (a party, species, move,
  status, stage, resource, ...) rewrites the saved scenarios in the same
  undo step (follow_rename(), through the project's scenario Documents:
  BattleProject.scenarios, saved with Save all); validate() with a project
  also reports names the battle data does not have (unknown_names());
- "scenario + expected transcript" for regression tests (the engine's
  check_expected()), and the text forms the panel and the CLI use for
  choices, answers, stages and name lists.

The bench is built from the battle data as saved: unsaved edits reach it
after the next save. Building needs CMake and a C++ compiler (toolchain()
says what is missing); everything else works without them. No Qt.
"""
from __future__ import annotations

import copy
import inspect
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

from . import codepage, engine, manifest_io, templates
from .document import Document, DocumentError, group

if TYPE_CHECKING:
   from .battle import BattleProject

## A parsed JSON object (a scenario, a party, a bench record).
JsonDict = dict[str, Any]
## A progress callback: (phase, text); phases are PHASES.
Progress = Callable[[str, str], None]

## Scenario schema (the engine's bench_scenario.SCHEMA).
SCHEMA = "capsule.bench/1"
## Folder of a game's scenarios (relative to the game folder).
SCENARIO_FOLDER = "bench"
## File name ending of a scenario.
SCENARIO_SUFFIX = ".json"
## File name ending of a scenario's expected transcript (beside it: NAME.expected.txt).
EXPECTED_SUFFIX = ".expected.txt"
## The bench's build folder, relative to the game folder (one sub-folder per generator).
CACHE_FOLDER = ("build", "bench")
## The engine tool that owns scenarios, the build and the output (tools/bench_scenario.py).
TOOL = "bench_scenario"
## Its file inside the engine.
TOOL_FILE = ("tools", "bench_scenario.py")
## The generator a run uses unless told otherwise: the engine's own (no source file).
DEFAULT_RNG = "default"
## The reference repo's folder of compatibility modules (its generators manifest, the tool's GENERATORS_FILE,
## lies in it: compat/generators.json, capsule.generators/1).
COMPAT_FOLDER = "compat"
## Seed of a new scenario.
DEFAULT_SEED = 1
## The player's side and the foe's side of a new scenario.
PLAYER_SIDE, FOE_SIDE = 0, 1
## The controller of a new scenario's player party (one of the tool's CONTROLLERS; the foe's is the tool's
## DEFAULT_CONTROLLER).
PLAYER_CONTROLLER = "human"
## The party flag of a new scenario's lone foe creature (one of the tool's PARTY_FLAGS: nobody owns it).
UNOWNED_FLAG = "unowned"
## Progress phase: configuring a build folder (its first build).
PHASE_CONFIGURE = "configure"
## Progress phase: an incremental build.
PHASE_BUILD = "build"
## Progress phase: the bench runs.
PHASE_RUN = "run"
## Progress phase: finished.
PHASE_DONE = "done"
## Progress phase of one output line of the configure / build step (E7's build(progress=)).
PHASE_LOG = "log"
## Progress phases, in order.
PHASES = (PHASE_CONFIGURE, PHASE_BUILD, PHASE_LOG, PHASE_RUN, PHASE_DONE)
## The CMake cache file of a configured build folder.
CMAKE_CACHE = "CMakeCache.txt"
## Oldest CMake the engine takes (its CMakeLists.txt cmake_minimum_required).
CMAKE_MIN = (3, 24)
## C++ compilers looked for on PATH (CXX wins when set).
COMPILERS = ("c++", "g++", "clang++", "cl")
## Environment variable naming the C++ compiler (CMake reads it too).
CXX_ENV = "CXX"
## Environment variable giving cmake --build its job count.
JOBS_ENV = "CMAKE_BUILD_PARALLEL_LEVEL"
## Seconds the version check of cmake may take.
VERSION_TIMEOUT = 20
## A version number in `cmake --version`: groups major, minor.
VERSION_RE = re.compile(r"(?P<major>\d+)\.(?P<minor>\d+)")
## The record type of a trapped battler's turn choice (C5: the engine bench's TRAPPED_RECORD, is_trapped()).
TRAPPED_KIND = "trapped"
## Record types of the bench's output, in the order the event list's filters show them.
RECORD_KINDS = ("line", "rng", "vm", "event", "request", TRAPPED_KIND, "note", "stop", "error", "bench")
## How the tool's command line starts an error message (stderr).
ERROR_PREFIX = "error: "
## Separator of the choices of one turn in choice text (one per field position).
CHOICE_SEPARATOR = " | "
## Marker of a move's target in choice text ("move Strike @1").
TARGET_MARK = "@"
## Separator of a list of names, stages or flags in form text.
LIST_SEPARATOR = ","
## Kinds of a table cell: an integer, a name ("-": null), a list of names, stage pokes, volatile counters,
## resource values (D-25: "ep 5, uses 3/3/1": a battler resource's number, a move resource's value per slot).
CELL_KINDS = ("int", "name", "names", "stages", "counts", "pools")
## Separator of a move resource's values per move slot in form text.
SLOT_SEPARATOR = "/"
## Columns of the party table: (scenario key, cell kind).
PARTY_COLUMNS = (("side", "int"), ("controller", "name"), ("flags", "names"), ("data", "name"))
## Columns of the member table (a party's records).
MEMBER_COLUMNS = (("species", "name"), ("level", "int"), ("item", "name"), ("trait", "name"), ("moves", "names"),
                  ("hp", "int"), ("status", "name"), ("resources", "pools"))
## Columns of the poke table (battler values right after the start; "status_counter" / "status_aux": the status's
## counter and scratch, the engine's generic names since C1; "counters": {volatile name: its counter}).
POKE_COLUMNS = (("party", "int"), ("member", "int"), ("hp", "int"), ("status", "name"), ("status_counter", "int"),
                ("status_aux", "int"), ("counters", "counts"), ("item", "name"), ("volatiles", "names"),
                ("stages", "stages"), ("resources", "pools"))


class _NoneValue:
   """!A cell meaning JSON null (an empty cell means "absent")."""


## The value cell_value() gives for "-" (JSON null).
NONE_VALUE = _NoneValue()


class BenchError(DocumentError):
   """!A scenario, build or run problem (the message says what)."""


class ToolchainMissing(BenchError):
   """!The bench cannot be built here: CMake or a C++ compiler is missing.

   @var missing
   What is missing, one item each.
   """

   def __init__(self, missing: list[str]) -> None:
      """!Names what is missing.
      @param missing  one item each
      """
      super().__init__(toolchain_text(missing))
      ## What is missing, one item each.
      self.missing = missing


class Cancelled(BenchError):
   """!The run was cancelled (Runner.cancel())."""


def tool() -> ModuleType:
   """!The engine's bench tool (tools/bench_scenario.py).
   @return the module
   @throws engine.EngineNotFound when no engine is found
   """
   return engine.tool(TOOL)


def traces() -> list[str]:
   """!The trace names a scenario or a run turns on (the tool's TRACES).
   @return names, in the tool's order
   """
   return list(tool().TRACES)


def controllers() -> list[str]:
   """!A party's controllers (the tool's CONTROLLERS; the first is its DEFAULT_CONTROLLER).
   @return names
   """
   return list(tool().CONTROLLERS)


def foe_controller() -> str:
   """!The controller of a party that states none, and of a new scenario's foe (the tool's DEFAULT_CONTROLLER).
   @return the name
   """
   return str(tool().DEFAULT_CONTROLLER)


def party_flags() -> list[str]:
   """!A party's flags (the tool's PARTY_FLAGS).
   @return names, sorted
   """
   return sorted(tool().PARTY_FLAGS)


def answer_kinds() -> list[str]:
   """!The request kinds an answer names (the tool's ANSWER_KINDS).
   @return names, sorted
   """
   return sorted(tool().ANSWER_KINDS)


def stop_kinds() -> list[str]:
   """!How a run stops: the tool's STOP_KINDS ("end", its STOP_END, or a count of turns or steps).
   @return names, the default first
   """
   return list(tool().STOP_KINDS)


def is_generator_name(name: Any) -> bool:
   """!Whether a value is a generator name (the tool's RNG_NAME: a scenario's "rng", a build folder's name).
   @param name  the value
   @return True for one
   """
   return isinstance(name, str) and tool().RNG_NAME.fullmatch(name) is not None


def retired_poke_keys() -> dict[str, str]:
   """!The poke keys the bench no longer takes, with their new names (the tool's RETIRED_POKE_KEYS, C1:
   status_turns -> status_counter, escalation -> status_aux).
   @return {old: new}
   """
   return dict(tool().RETIRED_POKE_KEYS)


def _tool_error(e: Exception) -> BenchError:
   """!A tool exception as a BenchError.
   @param e  the tool's BenchError
   @return BenchError with its message
   """
   return BenchError(str(e))


# -- places -----------------------------------------------------------------------------------------------------------

def game_folder(project: BattleProject) -> Path:
   """!The game folder the battle data belongs to: the folder of its reference/project.json's reference/ folder,
   or the battle manifest's folder when it is in no game.
   @param project  BattleProject
   @return folder
   """
   found = codepage.find_project(project.battle.path)
   return found.parent.parent if found is not None else project.battle.path.parent


def scenario_folder(project: BattleProject) -> Path:
   """!Where the game's scenarios are (game folder / bench).
   @param project  BattleProject
   @return folder (may not exist yet)
   """
   return game_folder(project) / SCENARIO_FOLDER


def cache_folder(project: BattleProject, rng: str = DEFAULT_RNG) -> Path:
   """!The bench's build folder for one generator (game folder / build / bench / RNG).
   @param project  BattleProject
   @param rng      a generator name (generators())
   @return folder (may not exist yet)
   """
   return game_folder(project).joinpath(*CACHE_FOLDER, rng)


# -- generators -------------------------------------------------------------------------------------------------------

def reference_generators() -> dict[str, Path]:
   """!The generators the reference repo provides: its compat/generators.json (capsule.generators/1, read by the
   engine's bench_scenario.load_generators()), when the reference repo is found (core.templates.reference_root()).
   @return {name: source file} ({} without the reference repo or its manifest)
   @throws BenchError when the manifest is malformed (the tool's message)
   """
   ref = templates.reference_root()
   if ref is None:
      return {}
   manifest = ref / COMPAT_FOLDER / tool().GENERATORS_FILE
   if not manifest.is_file():
      return {}
   try:
      return dict(tool().load_generators(manifest))
   except Exception as e:   # the tool's BenchError
      raise BenchError(str(e)) from None


def generators(project: BattleProject | None = None) -> dict[str, Path | None]:
   """!The generators a bench can link: the engine's (DEFAULT_RNG, no source file) and the reference repo's
   (reference_generators()).
   @param project  BattleProject (unused: a game declares no generators of its own; kept for the callers)
   @return {name: source file, or None for DEFAULT_RNG}, in that order
   @throws BenchError when the reference repo's manifest is malformed
   """
   out: dict[str, Path | None] = {DEFAULT_RNG: None}
   for name, path in reference_generators().items():
      out.setdefault(name, path)
   return out


def generators_or_default(project: BattleProject | None = None) -> tuple[dict[str, Path | None], str | None]:
   """!generators(), or only the engine's generator when the reference repo's manifest is malformed (C4: the
   bench page and the CLI go on with the default generator and report the manifest's problem).
   @param project  BattleProject (see generators())
   @return ({name: source file, or None for DEFAULT_RNG}, the manifest's problem or None)
   """
   try:
      return generators(project), None
   except BenchError as e:
      return {DEFAULT_RNG: None}, str(e)


def generator_source(project: BattleProject, rng: str) -> Path | None:
   """!The source file of a generator.
   @param project  BattleProject
   @param rng      a generator name
   @return the file, or None for DEFAULT_RNG
   @throws BenchError for a generator neither the engine nor the reference repo provides
   """
   if rng == DEFAULT_RNG:
      return None   # the engine's own: the reference repo's manifest is not read (it may be malformed, C4)
   found = generators(project)
   if rng not in found:
      raise BenchError(f"unknown generator {rng!r} (available: {', '.join(found)}; the reference repo declares "
                       f"its generators in {COMPAT_FOLDER}/{tool().GENERATORS_FILE})")
   return found[rng]


def relative_name(project: BattleProject, path: str | Path) -> str:
   """!A scenario's name as the panel and the CLI show it: its path relative to the game folder.
   @param project  BattleProject
   @param path     the scenario file
   @return e.g. "bench/wild.json" (the absolute path when it is outside the game folder)
   """
   p = Path(path).resolve()
   try:
      return p.relative_to(game_folder(project).resolve()).as_posix()
   except ValueError:
      return str(p)


def scenario_paths(project: BattleProject) -> list[Path]:
   """!The game's scenario files (bench/*.json whose schema is capsule.bench/1), by name.
   @param project  BattleProject
   @return files
   """
   folder = scenario_folder(project)
   if not folder.is_dir():
      return []
   found = []
   for p in sorted(folder.glob("*" + SCENARIO_SUFFIX)):
      try:
         data = json.loads(p.read_text(encoding="utf-8"))
      except (OSError, ValueError):
         found.append(p)   # listed, so its problem can be seen and fixed
         continue
      if isinstance(data, dict) and data.get("schema") == SCHEMA:
         found.append(p)
   return found


def resolve(project: BattleProject, name: str | Path) -> Path:
   """!A scenario file from what a user typed: a path relative to the game folder ("bench/x.json"), a bare name
   ("x" or "x.json", in bench/), or a path relative to the current folder or absolute.
   @param project  BattleProject
   @param name     the name
   @return the file
   @throws BenchError when there is no such scenario
   """
   text = str(name)
   tries = [game_folder(project) / text, scenario_folder(project) / text,
            scenario_folder(project) / (text + SCENARIO_SUFFIX), Path(text)]
   for p in tries:
      if p.is_file():
         return p.resolve()
   known = ", ".join(relative_name(project, p) for p in scenario_paths(project)) or "none"
   raise BenchError(f"no scenario {text!r} (scenarios: {known})")


# -- scenarios --------------------------------------------------------------------------------------------------------

def new_scenario(project: BattleProject, name: str, format_name: str | None = None,
                 parties: Sequence[str] | None = None, seed: int = DEFAULT_SEED) -> JsonDict:
   """!A new scenario from the battle data: the player's side (human) and the foe's (ai), each a party of the
   data; without parties, the player gets the data's first party and the foe its second, or a wild creature of
   the first species when the data has fewer.
   @param project      BattleProject
   @param name         the transcript's title
   @param format_name  a format of the data, or None for the first
   @param parties      party names of the data: the player's, then the foe's (at most one per side), or None
   @param seed         the battle seed
   @return the scenario (valid; the bench resolves the names)
   @throws BenchError when a name is not in the battle data or the data has no species
   """
   formats = project.names("formats")
   known = project.names("parties")
   species = project.names("species")
   if format_name is not None and format_name not in formats:
      raise BenchError(f"no format {format_name!r} (formats: {', '.join(formats) or 'none'})")
   picked = list(parties) if parties is not None else known[:FOE_SIDE + 1]
   for p in picked:
      if p not in known:
         raise BenchError(f"no party {p!r} in the battle data (parties: {', '.join(known) or 'none'})")
   if len(picked) > FOE_SIDE + 1:
      raise BenchError("a new scenario takes at most two parties: the player's and the foe's")
   out: JsonDict = {"schema": SCHEMA, "name": name}
   if format_name is not None:
      out["format"] = format_name
   out["seed"] = seed
   rows = []
   for side in (PLAYER_SIDE, FOE_SIDE):
      row: JsonDict = {"side": side, "controller": PLAYER_CONTROLLER if side == PLAYER_SIDE else foe_controller()}
      if side < len(picked):
         row["data"] = picked[side]
      elif species:
         if side == FOE_SIDE:
            row["flags"] = [UNOWNED_FLAG]   # a lone creature nobody owns
         row["members"] = [{"species": species[0], "level": new_member_level(project)}]
      else:
         raise BenchError("the battle data has no species to put in a scenario")
      rows.append(row)
   out["parties"] = rows
   problems = validate(out)
   if problems:
      raise BenchError("; ".join(problems))
   return out


def validate(scenario: Any, project: BattleProject | None = None) -> list[str]:
   """!A scenario's problems: its shape (the engine's bench_scenario.validate()), then, with a project whose data
   compiles, its pokes' names against the data (bench_scenario.check_names(): volatiles, counters of volatiles
   that have one, stages and each stage's range, statuses, items) and every other name it uses (unknown_names(),
   with or without a compiling project).
   @param scenario  the parsed scenario
   @param project   BattleProject, or None for the shape only
   @return "path: message" per problem; empty when well formed
   """
   problems = tool().validate(scenario)
   if problems or project is None:
      return problems
   compiled, _error = project.compile()
   found = tool().check_names(scenario, compiled) if compiled is not None else []
   # Every other name too (formats, parties, species, moves, ...: the bench would refuse them when it runs), from
   # the Documents as they are now; a place the engine's check reported already is not reported twice.
   for where, text in unknown_names(scenario, project):
      if not any(p == where or p.startswith(where + ".") or p.startswith(where + ":") for p in found):
         found.append(f"{where}: {text}")
   return found + passive_slot_problems(scenario, project)


## A scenario member's passive slot (the tool's MEMBER_KEYS: an index into the structure's passive slots).
MEMBER_SLOT_KEY = "passive_slot"


def passive_slot_problems(scenario: Any, project: BattleProject) -> list[str]:
   """!The members whose passive slot the structure does not have (0 to the passive slots' count - 1; the
   tool's validate() allows any byte).
   @param scenario  the parsed scenario
   @param project   BattleProject
   @return "path: message" per member
   """
   from .structure import passive_slots   # local: core.structure imports core.battle, which imports core.logic
   names = passive_slots.slot_names(project.structure)
   top = len(names) - 1
   out = []
   parties = scenario.get("parties") if isinstance(scenario, dict) else None
   for p, party in enumerate(parties if isinstance(parties, list) else []):
      members = party.get("members") if isinstance(party, dict) else None
      for m, member in enumerate(members if isinstance(members, list) else []):
         v = member.get(MEMBER_SLOT_KEY) if isinstance(member, dict) else None
         if isinstance(v, int) and not isinstance(v, bool) and not 0 <= v <= top:
            out.append(f"parties[{p}].members[{m}].{MEMBER_SLOT_KEY}: 0 to {top} (the passive slots "
                       f"{', '.join(names)})")
   return out


# -- names a scenario uses (renames follow them) -------------------------------------------------------------------

## The battle data's lists a scenario names (core.logic.name_lists() / BattleProject.names() keys).
SCENARIO_LISTS = ("formats", "weathers", "parties", "species", "moves", "traits", "items", "statuses", "resources",
                  "volatiles", "stages", "ai_profiles")
## The lists BattleProject.names() gives (the others are core.logic.name_lists()').
CONTENT_LISTS = ("formats", "weathers", "parties", "species", "moves", "traits", "items", "statuses")
## The names a list's word is (messages: "unknown party 'x'").
LIST_WORDS = {"formats": "format", "weathers": "weather", "parties": "party", "species": "species", "moves": "move",
              "traits": "trait", "items": "item", "statuses": "status", "resources": "resource",
              "volatiles": "volatile", "stages": "stage", "ai_profiles": "AI profile"}
## The poke key of the general counters object.
COUNTERS_KEY = "counters"


@dataclass
class NameSlot:
   """!One place a scenario names an entry of the battle data."""
   ## Path in the scenario ("parties[0].members[1].species").
   where: str
   ## The list the name is from (SCENARIO_LISTS).
   list_key: str
   ## The name written there.
   name: str
   ## Writes another name there (a key keeps its place in its object).
   put: Callable[[str], None]


def _value_slot(where: str, key_list: str, holder: Any, key: Any) -> list[NameSlot]:
   """!The slot of a value naming an entry (a name: nothing for null or a slot number).
   @param where     path
   @param key_list  the list (SCENARIO_LISTS)
   @param holder    dict or list holding it
   @param key       its key or index
   @return [NameSlot] or []
   """
   value = holder[key]
   if not isinstance(value, str):
      return []

   def put(new: str) -> None:
      """!Writes the new name.
      @param new  name
      @return None
      """
      holder[key] = new
   return [NameSlot(where, key_list, value, put)]


def _key_slots(where: str, key_list: str, holder: Any) -> list[NameSlot]:
   """!The slots of an object's keys naming entries ({"mp": 5}, {"accuracy": -1}).
   @param where     path of the object
   @param key_list  the list
   @param holder    the object
   @return slots
   """
   if not isinstance(holder, dict):
      return []
   out = []
   for name in list(holder):
      def put(new: str, old: str = name) -> None:
         """!Renames the key in place (the object keeps its order).
         @param new  name
         @param old  the key
         @return None
         """
         items = [(new if k == old else k, v) for k, v in holder.items()]
         holder.clear()
         holder.update(items)
      out.append(NameSlot(f"{where}.{name}", key_list, name, put))
   return out


def name_slots(scenario: Any) -> list[NameSlot]:
   """!Every place a scenario names an entry of the battle data: the format, the field's weather, each party of
   the data, each member's species, moves, trait, item, status and resources, each poke's status, item,
   volatiles, counters, stages and resources, and the moves the choices name.
   @param scenario  the parsed scenario (any shape: what is not where a name goes is left out)
   @return slots, in scenario order
   """
   if not isinstance(scenario, dict):
      return []
   out: list[NameSlot] = []
   if "format" in scenario:
      out += _value_slot("format", "formats", scenario, "format")
   fld = scenario.get("field")
   if isinstance(fld, dict) and "weather" in fld:
      out += _value_slot("field.weather", "weathers", fld, "weather")
   parties = scenario.get("parties") if isinstance(scenario.get("parties"), list) else []
   for p, party in enumerate(parties):
      if not isinstance(party, dict):
         continue
      where = f"parties[{p}]"
      if "data" in party:
         out += _value_slot(f"{where}.data", "parties", party, "data")
      if "ai" in party:   # G1: the party's AI profile
         out += _value_slot(f"{where}.ai", "ai_profiles", party, "ai")
      members = party.get("members") if isinstance(party.get("members"), list) else []
      for m, member in enumerate(members):
         if not isinstance(member, dict):
            continue
         at = f"{where}.members[{m}]"
         for key, key_list in (("species", "species"), ("trait", "traits"), ("item", "items"),
                               ("status", "statuses")):
            if key in member:
               out += _value_slot(f"{at}.{key}", key_list, member, key)
         moves = member.get("moves") if isinstance(member.get("moves"), list) else []
         for i in range(len(moves)):
            out += _value_slot(f"{at}.moves[{i}]", "moves", moves, i)
         out += _key_slots(f"{at}.resources", "resources", member.get("resources"))
   pokes = scenario.get("pokes") if isinstance(scenario.get("pokes"), list) else []
   for k, poke in enumerate(pokes):
      if not isinstance(poke, dict):
         continue
      where = f"pokes[{k}]"
      for key, key_list in (("status", "statuses"), ("item", "items")):
         if key in poke:
            out += _value_slot(f"{where}.{key}", key_list, poke, key)
      vols = poke.get("volatiles") if isinstance(poke.get("volatiles"), list) else []
      for i in range(len(vols)):
         out += _value_slot(f"{where}.volatiles[{i}]", "volatiles", vols, i)
      out += _key_slots(f"{where}.{COUNTERS_KEY}", "volatiles", poke.get(COUNTERS_KEY))
      out += _key_slots(f"{where}.stages", "stages", poke.get("stages"))
      out += _key_slots(f"{where}.resources", "resources", poke.get("resources"))
   choices = scenario.get("choices") if isinstance(scenario.get("choices"), list) else []
   for t, turn in enumerate(choices):
      picks = turn if isinstance(turn, list) else [turn]
      for j, pick in enumerate(picks):
         if isinstance(pick, dict) and "move" in pick:
            at = f"choices[{t}]" + (f"[{j}]" if isinstance(turn, list) else "")
            out += _value_slot(f"{at}.move", "moves", pick, "move")
   return out


def known_names(project: BattleProject) -> dict[str, list[str]]:
   """!The names each SCENARIO_LISTS list holds now (unsaved edits included).
   @param project  BattleProject
   @return {list: names}
   """
   from . import logic   # local: core.logic imports the battle modules
   lists = logic.name_lists(project)
   return {key: project.names(key) if key in CONTENT_LISTS else lists.get(key, []) for key in SCENARIO_LISTS}


def unknown_names(scenario: Any, project: BattleProject) -> list[tuple[str, str]]:
   """!The names a scenario uses that the battle data does not have (a rename that did not follow, an entry
   removed since).
   @param scenario  the parsed scenario
   @param project   BattleProject
   @return [(path, "unknown party 'Novice Kit'")]
   """
   known = known_names(project)
   return [(s.where, f"unknown {LIST_WORDS[s.list_key]} {s.name!r}") for s in name_slots(scenario)
           if s.name not in known[s.list_key]]


def follow_rename(project: BattleProject | None, key_list: str, old: str, new: str, label: str) -> list[str]:
   """!Renames an entry in the game's saved bench scenarios (and the scenarios open in the project): each scenario
   naming it is edited as the project's Document (BattleProject.scenario()), inside the edit running now, so the
   rename is one undo step with the manifests and the scenarios are saved (and counted unsaved) with them. A file
   that is not a readable scenario is left alone (its validation says so).
   @param project   BattleProject (None: nothing to follow)
   @param key_list  the list the name is from (SCENARIO_LISTS; another list names nothing in a scenario)
   @param old       the name
   @param new       the new name
   @param label     undo label
   @return "bench/x.json: parties[0].data" per place rewritten
   """
   if project is None or key_list not in SCENARIO_LISTS or old == new:
      return []

   def names_it(data: Any) -> bool:
      """!Whether a scenario names the entry.
      @param data  the scenario
      @return True when it does
      """
      return any(s.list_key == key_list and s.name == old for s in name_slots(data))

   found = []
   for doc in _scenario_documents(project, names_it):
      with doc.edit(label):
         hits = [s for s in name_slots(doc.data) if s.list_key == key_list and s.name == old]
         for s in hits:
            s.put(new)
      found += [f"{relative_name(project, doc.path)}: {s.where}" for s in hits]
   return found


def _scenario_files(project: BattleProject, wanted: Callable[[Any], bool]) -> list[Path]:
   """!The saved (and open) scenarios a test picks (an open one as its Document holds it now).
   @param project  BattleProject
   @param wanted   callable(scenario data) -> True for a scenario wanted
   @return their files (resolved)
   """
   paths = scenario_paths(project)
   paths += [p for p in project.scenarios if p not in paths]
   out = []
   for path in paths:
      key = Path(path).resolve()
      opened = project.scenarios   # local name for "in": Doxygen 1.12 misreads "in self.x"
      if key in opened:
         data = opened[key].data
      else:
         try:
            data = manifest_io.load(key)
         except (OSError, ValueError):
            continue
      if wanted(data) and key not in out:
         out.append(key)
   return out


def _scenario_documents(project: BattleProject, wanted: Callable[[Any], bool]) -> list[Document]:
   """!The project's Documents of the saved (and open) scenarios a test picks.
   @param project  BattleProject
   @param wanted   callable(scenario data) -> True for a scenario to edit
   @return Documents (BattleProject.scenario(): edited inside the edit running now, saved with the project)
   """
   out = []
   for key in _scenario_files(project, wanted):
      try:
         out.append(project.scenario(key))
      except DocumentError:
         continue
   return out


def _scenario_members(scenario: Any) -> list[JsonDict]:
   """!The members a scenario's parties list.
   @param scenario  the parsed scenario (any shape)
   @return member dicts
   """
   parties = scenario.get("parties") if isinstance(scenario, dict) else None
   out = []
   for party in parties if isinstance(parties, list) else []:
      members = party.get("members") if isinstance(party, dict) else None
      out += [m for m in (members if isinstance(members, list) else []) if isinstance(m, dict)]
   return out


def follow_passive_slots(project: BattleProject | None, remap: Callable[[int], int | None], label: str) -> list[str]:
   """!Renumbers the members' passive slot in the saved bench scenarios after the passive slots changed
   (core.structure.passive_slots), inside the edit running now (one undo step with the manifests).
   @param project  BattleProject (None: nothing to follow)
   @param remap    old index -> new index, or None: the slot went (the member falls back to the first)
   @param label    undo label
   @return "bench/x.json: parties[0].members[1]" per member rewritten
   """
   if project is None:
      return []
   key = MEMBER_SLOT_KEY

   def changes(data: Any) -> bool:
      """!Whether a scenario has a member whose number changes.
      @param data  the scenario
      @return True when one does
      """
      return any(isinstance(m.get(key), int) and remap(m[key]) != m[key] for m in _scenario_members(data))

   found = []
   for doc in _scenario_documents(project, changes):
      with doc.edit(label):
         for n, m in enumerate(_scenario_members(doc.data)):
            if not isinstance(m.get(key), int) or remap(m[key]) == m[key]:
               continue
            new = remap(m[key])
            if new is None:
               m.pop(key)
            else:
               m[key] = new
            found.append(f"{relative_name(project, doc.path)}: member {n}")
   return found


def retired_keys_in(scenario: Any) -> list[str]:
   """!The poke keys a scenario still writes under their retired names (retired_poke_keys()).
   @param scenario  the parsed scenario (any shape)
   @return "pokes[0].status_turns" per key
   """
   pokes = scenario.get("pokes") if isinstance(scenario, dict) else None
   retired = retired_poke_keys()
   return [f"pokes[{k}].{old}" for k, poke in enumerate(pokes if isinstance(pokes, list) else [])
           if isinstance(poke, dict) for old in retired if old in poke]


def migrate_scenario(scenario: Any) -> list[str]:
   """!Renames a scenario's retired poke keys in place (each keeps its place in its poke; a poke stating both
   names keeps the new one).
   @param scenario  the parsed scenario (live: call it inside its Document's edit)
   @return "pokes[0].status_turns -> status_counter" per key
   """
   pokes = scenario.get("pokes") if isinstance(scenario, dict) else None
   done = []
   for k, poke in enumerate(pokes if isinstance(pokes, list) else []):
      if not isinstance(poke, dict):
         continue
      for old, new in retired_poke_keys().items():
         if old not in poke:
            continue
         if new in poke:
            del poke[old]   # the new name wins
         else:
            items = [(new if key == old else key, v) for key, v in poke.items()]
            poke.clear()
            poke.update(items)
         done.append(f"pokes[{k}].{old} -> {new}")
   return done


def scenarios_to_migrate(project: BattleProject) -> list[str]:
   """!The saved (and open) scenarios that still write retired poke keys (the panel offers to migrate them).
   @param project  BattleProject
   @return their names (relative_name())
   """
   return [relative_name(project, f) for f in _scenario_files(project, lambda data: bool(retired_keys_in(data)))]


def migrate_scenarios(project: BattleProject, label: str = "Migrate bench scenarios") -> list[str]:
   """!Migrates every saved (and open) scenario's retired poke keys as the project's Documents (unsaved until Save
   all; one undo step for them all).
   @param project  BattleProject
   @param label    undo label of each scenario's edit
   @return "bench/x.json: pokes[0].status_turns -> status_counter" per key
   """
   found = []
   with group(label):
      for doc in _scenario_documents(project, lambda data: bool(retired_keys_in(data))):
         with doc.edit(label):
            found += [f"{relative_name(project, doc.path)}: {what}" for what in migrate_scenario(doc.data)]
   return found


def open_scenario(path: str | Path) -> Document:
   """!Opens a scenario file as a Document (undo, saving).
   @param path  the file
   @return Document (schema capsule.bench/1)
   @throws DocumentError when it is not a scenario
   """
   try:
      return Document.open(path, SCHEMA)
   except BenchError:
      raise
   except (OSError, ValueError, DocumentError) as e:
      raise BenchError(f"{Path(path).name}: {e}") from e


def create(project: BattleProject, name: str, **options: Any) -> Document:
   """!Writes a new scenario to bench/NAME.json (see new_scenario()).
   @param project  BattleProject
   @param name     file name stem and transcript title
   @param options  new_scenario()'s format_name, parties, seed
   @return the saved Document (BattleProject.scenarios holds it)
   @throws BenchError when the name is taken or not a plain file name
   """
   stem = name.strip()
   if not stem or Path(stem).name != stem or stem.startswith("."):
      raise BenchError(f"{name!r}: a scenario name is a plain file name (no folders)")
   if stem.endswith(SCENARIO_SUFFIX):
      stem = stem[:-len(SCENARIO_SUFFIX)]
   path = scenario_folder(project) / (stem + SCENARIO_SUFFIX)
   if path.exists():
      raise BenchError(f"{relative_name(project, path)} already exists")
   doc = Document(new_scenario(project, stem, **options), path, SCHEMA)
   doc.save()
   project.scenarios[doc.path] = doc   # the project's Document from now on (renames, Save all)
   return doc


def owner_texts_key() -> str:
   """!A scenario's switch for the owner texts in its transcript (the engine's bench_scenario OWNER_TEXTS_KEY,
   E13b: the transcript prints the text / volatile / side events of the effect logic; default off).
   @return the key
   """
   return str(tool().OWNER_TEXTS_KEY)


def owner_texts(scenario: Mapping[str, Any]) -> bool:
   """!Whether a scenario's transcript prints the owner texts (owner_texts_key(); E13b).
   @param scenario  parsed scenario
   @return True when on
   """
   return scenario.get(owner_texts_key()) is True


def set_owner_texts(doc: Document, on: bool) -> bool:
   """!Turns a scenario's owner texts on or off (off leaves the key out: the engine's default). Call inside
   doc.edit().
   @param doc  scenario Document
   @param on   print the owner texts
   @return True when it changed
   """
   if owner_texts(doc.data) == on:
      return False
   if on:
      doc.data[owner_texts_key()] = True
   else:
      doc.data.pop(owner_texts_key(), None)
   return True


def new_member_level(project: BattleProject, scenario: Mapping[str, Any] | None = None,
                     party: int | None = None) -> int:
   """!The level of a member the bench adds (S17: from the data, not a fixed number): the last member of the
   scenario's party, else the first member of the battle data's first party, else the data's highest level
   (rules.level_max); always within 1..level_max.
   @param project   BattleProject
   @param scenario  the scenario, or None
   @param party     index of the party the member joins, or None
   @return level
   """
   from . import battle as battle_core   # local, as core.battle imports this module
   most = battle_core.level_max(project.structure)
   levels: list[Any] = []
   parties = scenario.get("parties") if isinstance(scenario, Mapping) else None
   if isinstance(parties, list) and party is not None and 0 <= party < len(parties):
      members = parties[party].get("members") if isinstance(parties[party], dict) else None
      levels += [m.get("level") for m in reversed(members) if isinstance(m, dict)] if isinstance(members, list) \
         else []
   for name in project.names("parties")[:1]:
      members = project.entry("parties", name).get("members")
      levels += [m.get("level") for m in members if isinstance(m, dict)] if isinstance(members, list) else []
   given = next((v for v in levels if isinstance(v, int) and not isinstance(v, bool)), most)
   return max(1, min(most, given))


def set_scenario(doc: Document, data: JsonDict) -> bool:
   """!Replaces a scenario's content (call inside doc.edit(); the schema stays).
   @param doc   scenario Document
   @param data  the new content
   @return True when it changed
   """
   new = copy.deepcopy(dict(data))
   new["schema"] = SCHEMA
   if new == doc.data:
      return False
   doc.data.clear()
   doc.data.update(new)
   return True


def expected_path(doc: Document) -> Path | None:
   """!The scenario's expected transcript file ("expect", relative to the scenario).
   @param doc  scenario Document
   @return the file, or None when it names none (or the scenario has no file)
   """
   rel = doc.data.get("expect")
   if not isinstance(rel, str) or doc.path is None:
      return None
   return doc.path.parent / rel


def expected_text(doc: Document) -> str | None:
   """!The scenario's expected transcript.
   @param doc  scenario Document
   @return its text, or None when it names none or the file is missing
   """
   p = expected_path(doc)
   if p is None or not p.is_file():
      return None
   return p.read_text(encoding="utf-8")


def save_expected(doc: Document, transcript: str) -> Path:
   """!Saves a transcript as the scenario's expected one: NAME.expected.txt beside the scenario (or the file
   "expect" already names), "expect" set (one undo step), the scenario saved.
   @param doc         scenario Document with a path
   @param transcript  the transcript text (BenchRun.transcript())
   @return the transcript file
   @throws BenchError when the scenario has no file
   """
   if doc.path is None:
      raise BenchError("save the scenario first")
   rel = doc.data.get("expect")
   if not isinstance(rel, str):
      stem = doc.path.name[:-len(SCENARIO_SUFFIX)] if doc.path.name.endswith(SCENARIO_SUFFIX) else doc.path.stem
      rel = stem + EXPECTED_SUFFIX
   out = doc.path.parent / rel
   out.parent.mkdir(parents=True, exist_ok=True)
   out.write_text(transcript, encoding="utf-8")
   if doc.data.get("expect") != rel:
      with doc.edit("Save as expected") as d:
         d["expect"] = rel
   if doc.dirty:
      doc.save()
   return out


def expected_problems(expected: str, transcript: str, name: str = "expected") -> list[str]:
   """!Compares a run's transcript with an expected one, as the engine's check_expected() reports it: the first
   differing line.
   @param expected    the expected text
   @param transcript  the run's text
   @param name        the expected file's name (for the message)
   @return problems; empty when they match
   """
   t = tool()
   if hasattr(t, "compare_transcripts"):   # E7: the engine's own comparison
      return list(t.compare_transcripts(expected, transcript, name))
   if expected == transcript:
      return []
   a, b = expected.splitlines(), transcript.splitlines()
   for i in range(max(len(a), len(b))):
      la = a[i] if i < len(a) else "<end>"
      lb = b[i] if i < len(b) else "<end>"
      if la != lb:
         return [f"{name}:{i + 1}\n  expected: {la}\n  bench:    {lb}"]
   return [f"{name}: differs only in line endings"]


# -- form text --------------------------------------------------------------------------------------------------------

def _is_int(v: Any) -> bool:
   """!Whether a JSON value is an integer (not a boolean).
   @param v  the value
   @return True for an int
   """
   return isinstance(v, int) and not isinstance(v, bool)


def choice_text(choice: Any) -> str:
   """!One turn's choice(s) as text: "first", "run", "move 2", "move Strike @1", "switch 1"; several (one per field
   position) joined by " | ".
   @param choice  a scenario choice, or a list of them
   @return the text
   """
   if isinstance(choice, list):
      return CHOICE_SEPARATOR.join(choice_text(c) for c in choice)
   if isinstance(choice, str):
      return choice
   if isinstance(choice, dict) and "move" in choice:
      text = f"move {choice['move']}"
      return text + (f" {TARGET_MARK}{choice['target']}" if "target" in choice else "")
   if isinstance(choice, dict) and "switch" in choice:
      return f"switch {choice['switch']}"
   return json.dumps(choice)


def _one_choice(text: str) -> Any:
   """!One choice from text (see choice_text()).
   @param text  e.g. "move Fireball @1"
   @return the scenario value
   @throws BenchError when it is not a choice
   """
   t = text.strip()
   if t in ("first", "run"):
      return t
   word, _sep, rest = t.partition(" ")
   rest = rest.strip()
   if word == "switch" and rest.isdigit():
      return {"switch": int(rest)}
   if word == "move" and rest:
      what, mark, target = rest.rpartition(TARGET_MARK)
      if not mark:
         what, target = rest, ""
      what = what.strip()
      if not what or (mark and not target.strip().isdigit()):
         raise BenchError(f"{text!r}: move SLOT|NAME [{TARGET_MARK}TARGET]")
      out: JsonDict = {"move": int(what) if what.isdigit() else what}
      if mark:
         out["target"] = int(target.strip())
      return out
   raise BenchError(f"{text!r}: a choice is first, run, move SLOT|NAME [{TARGET_MARK}TARGET] or switch MEMBER")


def parse_choice(text: str) -> Any:
   """!One turn's choice(s) from text (see choice_text()).
   @param text  the text
   @return a choice, or a list of them (one per field position)
   @throws BenchError when a part is not a choice
   """
   parts = text.split(CHOICE_SEPARATOR.strip())
   if len(parts) == 1:
      return _one_choice(parts[0])
   return [_one_choice(p) for p in parts]


def choices_text(choices: Iterable[Any]) -> str:
   """!Every turn's choices, one turn per line.
   @param choices  the scenario's "choices"
   @return the text
   """
   return "\n".join(choice_text(c) for c in choices)


def parse_choices(text: str) -> list[Any]:
   """!Every turn's choices from text (one turn per line; blank lines are skipped).
   @param text  the text
   @return the "choices" list
   @throws BenchError naming the line of a bad choice
   """
   out = []
   for n, line in enumerate(text.splitlines(), 1):
      if not line.strip():
         continue
      try:
         out.append(parse_choice(line))
      except BenchError as e:
         raise BenchError(f"choices line {n}: {e}") from e
   return out


def answers_text(answers: Iterable[Any]) -> str:
   """!Effect request answers, one per line: "learn_move 0", "switch_target 1", "choice 2".
   @param answers  the scenario's "answers"
   @return the text
   """
   lines = []
   for a in answers:
      if isinstance(a, dict) and len(a) == 1:
         kind, value = next(iter(a.items()))
         lines.append(f"{kind} {value}")
      else:
         lines.append(json.dumps(a))
   return "\n".join(lines)


def parse_answers(text: str) -> list[JsonDict]:
   """!Answers from text (see answers_text()).
   @param text  the text
   @return the "answers" list
   @throws BenchError naming the line of a bad answer
   """
   out = []
   for n, line in enumerate(text.splitlines(), 1):
      if not line.strip():
         continue
      kind, _sep, value = line.strip().partition(" ")
      if kind not in answer_kinds() or not value.strip().isdigit():
         raise BenchError(f"answers line {n}: {line.strip()!r}: KIND N with KIND one of "
                          f"{', '.join(answer_kinds())}")
      out.append({kind: int(value.strip())})
   return out


def names_text(names: Iterable[Any]) -> str:
   """!A list of names as text ("Strike, Fireball"; null as "-").
   @param names  names
   @return the text
   """
   return f"{LIST_SEPARATOR} ".join("-" if n is None else str(n) for n in names)


def parse_names(text: str) -> list[str | None]:
   """!A list of names from text (see names_text()).
   @param text  the text
   @return names ("-" is null: an empty move slot)
   """
   return [None if p.strip() == "-" else p.strip() for p in text.split(LIST_SEPARATOR) if p.strip()]


def stages_text(stages: Mapping[str, Any]) -> str:
   """!Stage pokes as text ("attack +2, defence -1").
   @param stages  {stage name: value}
   @return the text
   """
   return f"{LIST_SEPARATOR} ".join(f"{k} {v:+d}" if _is_int(v) else f"{k} {v}" for k, v in stages.items())


def parse_stages(text: str) -> dict[str, int]:
   """!Stage pokes from text (see stages_text()).
   @param text  the text
   @return {stage name: value}
   @throws BenchError when a part is not "NAME VALUE"
   """
   out = {}
   for part in text.split(LIST_SEPARATOR):
      if not part.strip():
         continue
      name, _sep, value = part.strip().rpartition(" ")
      try:
         out[name.strip()] = int(value)
      except ValueError:
         raise BenchError(f"{part.strip()!r}: a stage is NAME VALUE (e.g. attack +2)") from None
      if not name.strip():
         raise BenchError(f"{part.strip()!r}: a stage is NAME VALUE (e.g. attack +2)")
   return out


def counts_text(counts: Mapping[str, Any]) -> str:
   """!Counter pokes as text ("confusion 2, protect_chain 1").
   @param counts  {volatile name: counter}
   @return the text
   """
   return f"{LIST_SEPARATOR} ".join(f"{k} {v}" for k, v in counts.items())


def pools_text(pools: Mapping[str, Any]) -> str:
   """!Resource values as text ("ep 5, uses 3/3/1"; a move resource's values per slot joined by SLOT_SEPARATOR).
   @param pools  {resource name: n or [n per move slot]}
   @return the text
   """
   return f"{LIST_SEPARATOR} ".join(
      f"{k} {SLOT_SEPARATOR.join(str(x) for x in v)}" if isinstance(v, list) else f"{k} {v}" for k, v in pools.items())


def parse_pools(text: str) -> dict[str, int | list[int]]:
   """!Resource values from text (see pools_text()): a value with SLOT_SEPARATOR is a list (one per move slot).
   @param text  the text
   @return {resource name: n or [n, ...]}
   @throws BenchError when a part is not "NAME VALUE" or "NAME V/V/..."
   """
   out: dict[str, int | list[int]] = {}
   for part in text.split(LIST_SEPARATOR):
      if not part.strip():
         continue
      name, _sep, value = part.strip().rpartition(" ")
      try:
         parts = [int(v) for v in value.split(SLOT_SEPARATOR)]
      except ValueError:
         raise BenchError(f"{part.strip()!r}: a resource is NAME VALUE or NAME V/V/... (one per move slot)") from None
      if not name.strip():
         raise BenchError(f"{part.strip()!r}: a resource is NAME VALUE or NAME V/V/... (one per move slot)")
      out[name.strip()] = parts if SLOT_SEPARATOR in value else parts[0]
   return out


def cell_text(value: Any, kind: str) -> str:
   """!A scenario value as a table cell's text.
   @param value  the value (None: absent)
   @param kind   one of CELL_KINDS
   @return the text ("" when absent; "-" for null)
   """
   if value is None:
      return ""
   if kind == "names" and isinstance(value, list):
      return names_text(value)
   if kind == "stages" and isinstance(value, dict):
      return stages_text(value)
   if kind == "counts" and isinstance(value, dict):
      return counts_text(value)
   if kind == "pools" and isinstance(value, dict):
      return pools_text(value)
   return str(value)


def cell_value(text: str, kind: str, column: str) -> Any:
   """!A table cell's text as a scenario value.
   @param text    the text ("" is absent)
   @param kind    one of CELL_KINDS
   @param column  its key (for messages)
   @return the value, or None when absent (a "name" cell's "-" is NONE_VALUE: JSON null)
   @throws BenchError when it is not a value of the kind
   """
   t = text.strip()
   if not t:
      return None
   if kind == "int":
      try:
         return int(t)
      except ValueError:
         raise BenchError(f"{column}: {t!r} is not a number") from None
   if kind == "names":
      return parse_names(t)
   if kind in ("stages", "counts"):
      return parse_stages(t)   # the same NAME VALUE list
   if kind == "pools":
      return parse_pools(t)
   return NONE_VALUE if t == "-" else t


def cells(row: Mapping[str, Any], columns: Sequence[tuple[str, str]]) -> list[str]:
   """!A party, member or poke as table cells.
   @param row      the scenario object
   @param columns  PARTY_COLUMNS, MEMBER_COLUMNS or POKE_COLUMNS
   @return one text per column
   """
   out = []
   for key, kind in columns:
      if key in row and row[key] is None:
         out.append("-")
      else:
         out.append(cell_text(row.get(key), kind))
   return out


def from_cells(texts: Sequence[str], columns: Sequence[tuple[str, str]],
               base: Mapping[str, Any] | None = None) -> JsonDict:
   """!A party, member or poke from table cells; the base's keys the table does not show are kept.
   @param texts    one text per column
   @param columns  PARTY_COLUMNS, MEMBER_COLUMNS or POKE_COLUMNS
   @param base     the object the row showed, or None
   @return the object (an empty cell leaves its key out)
   @throws BenchError naming the column of a bad cell
   """
   shown = {key for key, _kind in columns}
   out: JsonDict = {k: copy.deepcopy(v) for k, v in (base or {}).items() if k not in shown}
   keyed = {}
   for (key, kind), text in zip(columns, texts):
      value = cell_value(text, kind, key)
      if value is not None:
         keyed[key] = None if value is NONE_VALUE else value
   # Shown keys first, in column order, then the kept ones (as the base had them).
   return {**keyed, **out}


def trace_options(scenario: Mapping[str, Any]) -> list[str]:
   """!The traces a scenario asks for.
   @param scenario  the scenario
   @return names of traces() set to true
   """
   trace = scenario.get("trace") or {}
   return [t for t in traces() if isinstance(trace, dict) and trace.get(t) is True]


def parse_traces(text: str) -> list[str]:
   """!Trace names from the command line ("rng,vm").
   @param text  comma-separated names
   @return the names
   @throws BenchError on an unknown name
   """
   out = [t.strip() for t in text.split(LIST_SEPARATOR) if t.strip()]
   for t in out:
      if t not in traces():
         raise BenchError(f"unknown trace {t!r} ({', '.join(traces())})")
   return out


# -- toolchain --------------------------------------------------------------------------------------------------------

def toolchain_text(missing: Sequence[str]) -> str:
   """!What the bench needs, for a message.
   @param missing  what is missing
   @return text
   """
   return ("The bench is a compiled engine program: building it needs " + "; ".join(missing) +
           ". Install them (the studio's installer offers them) and run again; scenarios can be edited, "
           "validated and saved meanwhile.")


def toolchain() -> list[str]:
   """!What the bench's build needs and this machine lacks.
   @return missing items (empty: CMake and a C++ compiler are here)
   """
   missing = []
   cmake = shutil.which("cmake")
   if cmake is None:
      missing.append(f"CMake {CMAKE_MIN[0]}.{CMAKE_MIN[1]} or newer (cmake on PATH)")
   else:
      try:
         out = subprocess.run([cmake, "--version"], capture_output=True, text=True, timeout=VERSION_TIMEOUT).stdout
      except (OSError, subprocess.TimeoutExpired):
         out = ""
      m = VERSION_RE.search(out)
      if m is None or (int(m["major"]), int(m["minor"])) < CMAKE_MIN:
         found = m.group(0) if m is not None else "unknown"
         missing.append(f"CMake {CMAKE_MIN[0]}.{CMAKE_MIN[1]} or newer (found {found})")
   cxx = os.environ.get(CXX_ENV)
   if not (cxx and shutil.which(cxx.split()[0])) and not any(shutil.which(c) for c in COMPILERS):
      missing.append("a C++20 compiler (" + ", ".join(COMPILERS) + f" on PATH, or {CXX_ENV})")
   return missing


# -- results ----------------------------------------------------------------------------------------------------------

@dataclass
class TracePosition:
   """!Where a VM or RNG trace record points: its owner, hook and source position."""

   ## The owner as "kind:name" (core.logic's reference form), or "" when unknown.
   owner: str
   ## The hook (the top program's).
   hook: str
   ## The instruction.
   pc: int
   ## The source as the manifest lists it ("effects/moves.ceffect"), or "" for generated code / none.
   file: str = ""
   ## 1-based line, or 0.
   line: int = 0
   ## 1-based column, or 0.
   col: int = 0
   ## The condition template the code was expanded from (the bench's "template" key, E7: "status Poison"), or "".
   template: str = ""


def trace_position(record: Mapping[str, Any]) -> TracePosition | None:
   """!The owner, hook, pc and source position of a "vm" record (or an "rng" record drawn by effect code).
   @param record  a bench record
   @return TracePosition, or None when the record names no effect run
   """
   if "owner" not in record or "pc" not in record:
      return None
   owner = str(record["owner"])
   kind, _sep, name = owner.partition(" ")
   return TracePosition(f"{kind}:{name}" if name else "", str(record.get("hook", "")), int(record["pc"]),
                        str(record.get("file", "")), int(record.get("line", 0)), int(record.get("column", 0)),
                        str(record.get("template", "")))


@dataclass
class EventRow:
   """!One row of the event list."""

   ## Position of the record in the run's output.
   index: int
   ## Its type (RECORD_KINDS).
   kind: str
   ## The battle turn it happened in (the last turn seen before it for lines).
   turn: int
   ## What the row shows.
   text: str
   ## Random draws made since the previous transcript line (the line's draw marker; 0 for other rows).
   draws: int
   ## The record itself.
   record: JsonDict


def record_text(record: Mapping[str, Any]) -> str:
   """!A bench record as one line of text.
   @param record  the record
   @return text
   """
   kind = record.get("t")
   if kind == "line":
      return str(record.get("text", ""))
   where = ""
   pos = trace_position(record)
   if pos is not None:
      src = f" ({pos.file}:{pos.line}:{pos.col})" if pos.file else (" (generated)" if record.get("generated") else "")
      where = f"{record.get('owner')} {pos.hook} pc {pos.pc}{src}"
   if kind == "rng":
      return f"draw #{record.get('n')}: {record.get('value')} [{record.get('phase', '')}]" + (
         f" by {where}" if where else "")
   if kind == "vm":
      value = f" = {record['value']}" if "value" in record else ""
      sub = f" in {record['sub']}" if "sub" in record else ""
      return f"{record.get('op', '?')}{value}{sub}: {where}"
   if kind == "event":
      return (f"{record.get('kind')} battler {record.get('battler')} target {record.get('target')} "
              f"extra {record.get('extra')} a {record.get('a')} b {record.get('b')}")
   if kind == "request":
      how = "scripted" if record.get("scripted") else "default"
      return f"request {record.get('kind')} of battler {record.get('battler')}: answer {record.get('answer')} ({how})"
   if kind == TRAPPED_KIND:
      return (f"trapped: battler {record.get('battler')} on turn {record.get('turn')} (try_switch hooks keep it "
              "from switching out or running)")
   if kind == "note":
      return f"note: {record.get('message')}"
   if kind == "stop":
      return (f"stop: {record.get('reason')} after {record.get('steps')} steps, turn {record.get('turn')}, "
              f"outcome {record.get('outcome')}, {record.get('draws')} draws")
   if kind == "error":
      return f"error: {record['where']}: {record.get('message')}" if record.get("where") else \
         f"error: {record.get('message')}"
   if kind == "bench":
      return f"bench of {record.get('manifest')}, generator {record.get('rng')}: {record.get('scenario')}"
   return json.dumps(dict(record))


class BenchRun:
   """!What one bench run wrote (the engine's bench_scenario.Result), with the studio's views of it.

   @var result
   The tool's Result (status, records, stderr).
   @var rng
   The generator the bench was built with.
   @var status
   The bench's exit status (0: it ran the scenario).
   @var records
   Every record, in order.
   """

   def __init__(self, result: Any, rng: str = DEFAULT_RNG) -> None:
      """!Wraps a result.
      @param result  bench_scenario.Result
      @param rng     its generator
      """
      ## The tool's Result (status, records, stderr).
      self.result = result
      ## The generator the bench was built with.
      self.rng = rng
      ## The bench's exit status (0: it ran the scenario).
      self.status: int = result.status
      ## Every record, in order.
      self.records: list[JsonDict] = result.records

   @classmethod
   def from_output(cls, text: str, status: int = 0, stderr: str = "", rng: str = DEFAULT_RNG) -> BenchRun:
      """!A run from the bench's JSON lines (tests, saved output).
      @param text    JSON lines
      @param status  exit status
      @param stderr  error output
      @param rng     its generator
      @return BenchRun
      @throws BenchError when a line is not a record
      """
      return cls(_parse_result(status, text, stderr), rng)

   def of(self, kind: str) -> list[JsonDict]:
      """!The records of one type.
      @param kind  one of RECORD_KINDS
      @return them, in order
      """
      return self.result.of(kind)

   def transcript(self) -> str:
      """!The transcript in the golden format.
      @return text
      """
      return self.result.transcript()

   def errors(self) -> list[str]:
      """!The bench's error messages (and its stderr when it failed without any).
      @return messages
      """
      found = list(self.result.errors())
      if self.status != 0 and not found and self.result.stderr.strip():
         found.append(self.result.stderr.strip())
      return found

   def ok(self) -> bool:
      """!Whether the bench ran the scenario (exit 0, no error record).
      @return True when it did
      """
      return self.status == 0 and not self.result.errors()

   def events(self, kinds: Iterable[str] | None = None) -> list[EventRow]:
      """!The event list: each record as a row, transcript lines with the draws made since the line before.
      @param kinds  record types to keep (default every one but the "bench" header)
      @return rows, in order
      """
      keep = set(kinds) if kinds is not None else set(RECORD_KINDS) - {"bench"}
      rows = []
      draws = 0
      turn = 0
      for i, r in enumerate(self.records):
         kind = str(r.get("t"))
         if _is_int(r.get("turn")):
            turn = r["turn"]
         if kind == "rng":
            draws += 1
         marker = 0
         if kind == "line":
            marker, draws = draws, 0
         if kind in keep:
            rows.append(EventRow(i, kind, turn, record_text(r), marker, r))
      return rows

   def trace_positions(self) -> list[TracePosition]:
      """!Every VM record's position.
      @return positions, in order
      """
      return [p for p in (trace_position(r) for r in self.of("vm")) if p is not None]


# -- building and running ---------------------------------------------------------------------------------------------

def _parse_result(code: int, text: str, stderr: str) -> Any:
   """!The tool's Result of a bench run's output.
   @param code    exit status
   @param text    its JSON lines
   @param stderr  its error output
   @return bench_scenario.Result
   @throws BenchError when a line is not a record
   """
   t = tool()
   try:
      return t.Result(code, t.parse_output(text), stderr)
   except t.BenchError as e:
      raise _tool_error(e) from e


def _scenario_data(scenario: Document | Mapping[str, Any] | str | Path) -> tuple[JsonDict, Path | None]:
   """!A scenario's content and file.
   @param scenario  Document, parsed scenario or file
   @return (content, file or None)
   @throws BenchError when a file cannot be read
   """
   if isinstance(scenario, Document):
      return scenario.data, scenario.path
   if isinstance(scenario, Mapping):
      return dict(scenario), None
   path = Path(scenario)
   try:
      return json.loads(path.read_text(encoding="utf-8")), path
   except OSError as e:
      raise BenchError(f"{path}: cannot read ({e.strerror})") from e
   except ValueError as e:
      raise BenchError(f"{path}: {e}") from e


class Runner:
   """!Builds and runs the bench in child processes, so another thread can cancel either (cancel()).

   One Runner does one thing at a time; it is reusable after a cancel.

   @var _proc
   The child process running now, or None.
   """

   def __init__(self) -> None:
      """!An idle runner."""
      ## The child process running now, or None.
      self._proc: subprocess.Popen | None = None
      ## Guards _proc and _cancelled.
      self._lock = threading.Lock()
      ## Whether cancel() was called since the last start.
      self._cancelled = False

   @property
   def cancelled(self) -> bool:
      """!Whether cancel() was called during the current or last job.
      @return True when it was
      """
      return self._cancelled

   def reset(self) -> None:
      """!Clears a cancel (the next job runs).
      @return None
      """
      with self._lock:
         self._cancelled = False

   def cancel(self) -> None:
      """!Stops the build or the run (any thread): the child process and its children are killed; the job
      raises Cancelled.
      @return None
      """
      with self._lock:
         self._cancelled = True
         proc = self._proc
      if proc is not None and proc.poll() is None:
         _kill(proc)

   def _communicate(self, cmd: list[str], stdin: str | None = None, env: Mapping[str, str] | None = None,
                    timeout: float | None = None) -> subprocess.CompletedProcess:
      """!Runs a child process to its end (or a cancel).
      @param cmd      the command
      @param stdin    text for its input, or None
      @param env      its environment, or None for this one
      @param timeout  seconds, or None
      @return its exit status and output
      @throws Cancelled when cancelled; BenchError when it cannot start or times out
      """
      with self._lock:
         if self._cancelled:
            raise Cancelled("cancelled")
         try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                    env=dict(env) if env is not None else None, **_group_options())
         except OSError as e:
            raise BenchError(f"cannot start {Path(cmd[0]).name}: {e}") from e
         self._proc = proc
      try:
         out, err = proc.communicate(stdin, timeout=timeout)
      except subprocess.TimeoutExpired:
         _kill(proc)
         proc.communicate()
         raise BenchError(f"{Path(cmd[0]).name} took longer than {timeout} s") from None
      finally:
         with self._lock:
            self._proc = None
      if self._cancelled:
         raise Cancelled("cancelled")
      return subprocess.CompletedProcess(cmd, proc.returncode, out, err)

   def build(self, project: BattleProject, rng: str = DEFAULT_RNG, cache: str | Path | None = None,
             progress: Progress | None = None, jobs: int | None = None) -> Path:
      """!Builds the bench for the battle data as saved (the engine's bench_scenario build: configures the cache
      folder once per generator, then rebuilds incrementally).
      @param project   BattleProject
      @param rng       a generator name (generators(): a name other than DEFAULT_RNG links its source file)
      @param cache     the build folder (default cache_folder())
      @param progress  callback(phase, text), or None
      @param jobs      parallel compile jobs (default: every core)
      @return the bench executable
      @throws ToolchainMissing without CMake or a compiler; BenchError for an unknown generator, or with the
              compiler's output when the build fails; Cancelled
      """
      source = generator_source(project, rng)
      missing = toolchain()
      if missing:
         raise ToolchainMissing(missing)
      folder = Path(cache) if cache is not None else cache_folder(project, rng)
      first = not (folder / CMAKE_CACHE).is_file()
      if progress is not None:
         if first:
            progress(PHASE_CONFIGURE, f"configuring the bench in {relative_name(project, folder)} (the first build of "
                                "this folder compiles the engine's battle modules: a minute or two)")
         else:
            progress(PHASE_BUILD, "rebuilding the bench (only what changed since the last build)")
      t = tool()
      if hasattr(t, "BenchCancelled"):   # E7: build(progress=, cancel=, jobs=) in-process, cancellable
         return self._build_in_process(t, project, (rng, source), folder, progress, jobs)
      env = dict(os.environ)
      env[JOBS_ENV] = str(jobs if jobs is not None else (os.cpu_count() or 1))
      root = engine.root()
      cmd = [sys.executable, str(root.joinpath(*TOOL_FILE)), "build", str(project.battle.path),
             "--cache", str(folder), "--rng", rng, "--engine", str(root)]
      if source is not None:
         cmd += ["--rng-source", str(source)]
      done = self._communicate(cmd, env=env)
      text = done.stderr.strip()
      if done.returncode != 0:
         raise BenchError(text[len(ERROR_PREFIX):] if text.startswith(ERROR_PREFIX) else
                          text or f"build failed ({done.returncode})")
      printed = done.stdout.strip()
      exe = Path(printed.splitlines()[-1]) if printed else None
      if exe is None or not exe.is_file():
         raise BenchError(f"the build made no bench ({printed or 'no output'})")
      return exe

   def _build_in_process(self, t: ModuleType, project: BattleProject, rng: tuple[str, Path | None], folder: Path,
                         progress: Progress | None, jobs: int | None) -> Path:
      """!Builds with the engine tool's build(progress=, cancel=, jobs=, rng_source=) (E7, E11): its output lines go
      to the progress callback, Cancel stops the step it runs.
      @param t         the engine's bench_scenario module
      @param project   BattleProject
      @param rng       (generator name, its source file or None for DEFAULT_RNG)
      @param folder    the build folder
      @param progress  callback(phase, text), or None
      @param jobs      parallel compile jobs (default: every core)
      @return the bench executable
      @throws Cancelled; BenchError with the tool's message
      """
      lines = None if progress is None else (lambda line: progress(PHASE_LOG, line))
      name, source = rng
      try:
         exe = t.build(project.battle.path, folder, name, engine.root(),
                       jobs=jobs if jobs is not None else (os.cpu_count() or 1), progress=lines,
                       cancel=lambda: self._cancelled, rng_source=source)
      except t.BenchCancelled as e:
         raise Cancelled(str(e)) from None
      except t.BenchError as e:
         raise BenchError(str(e)) from None
      exe = Path(exe)
      if not exe.is_file():
         raise BenchError(f"the build made no bench ({exe})")
      return exe

   def run(self, bench: str | Path, scenario: Document | Mapping[str, Any] | str | Path,
           trace: Sequence[str] = (), rng: str = DEFAULT_RNG, progress: Progress | None = None) -> BenchRun:
      """!Runs the bench on a scenario (validated first; an unsaved Document's content is what runs).
      @param bench     the bench executable
      @param scenario  Document, parsed scenario or file
      @param trace     extra traces (traces()) besides the scenario's own
      @param rng       the generator the bench was built with (recorded in the result)
      @param progress  callback(phase, text), or None
      @return BenchRun
      @throws BenchError when the scenario is malformed or the bench cannot run; Cancelled
      """
      t = tool()
      for name in trace:
         if name not in traces():
            raise BenchError(f"unknown trace {name!r} ({', '.join(traces())})")
      data, _path = _scenario_data(scenario)
      problems = t.validate(data)
      if problems:
         raise BenchError("; ".join(problems))
      if progress is not None:
         progress(PHASE_RUN, "running the scenario")
      cmd = [str(bench), "-"] + (["--trace", LIST_SEPARATOR.join(trace)] if trace else [])
      done = self._communicate(cmd, stdin=json.dumps(data), timeout=t.RUN_TIMEOUT)
      result = BenchRun(_parse_result(done.returncode, done.stdout, done.stderr), rng)
      if progress is not None:
         progress(PHASE_DONE, "done" if result.ok() else "the bench reported errors")
      return result

   def build_and_run(self, project: BattleProject, scenario: Document | Mapping[str, Any] | str | Path,
                     rng: str | None = None, trace: Sequence[str] = (), progress: Progress | None = None,
                     cache: str | Path | None = None, jobs: int | None = None) -> BenchRun:
      """!Builds the bench (incrementally) and runs a scenario on it.
      @param project   BattleProject
      @param scenario  Document, parsed scenario or file
      @param rng       a generator name, or None for the scenario's "rng" (E7; else DEFAULT_RNG)
      @param trace     extra traces
      @param progress  callback(phase, text), or None
      @param cache     the build folder (default cache_folder())
      @param jobs      parallel compile jobs
      @return BenchRun
      @throws BenchError, ToolchainMissing, Cancelled
      """
      data, _path = _scenario_data(scenario)
      problems = validate(data)
      if problems:
         raise BenchError("; ".join(problems))   # before a build that may take a while
      rng = rng or scenario_rng(data)
      exe = self.build(project, rng, cache, progress, jobs)
      return self.run(exe, data, trace, rng, progress)


def _group_options() -> dict[str, Any]:
   """!Popen options that put a child in its own process group (cancel() kills the group: cmake, make, the
   compilers).
   @return keyword arguments
   """
   if os.name == "nt":
      return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
   return {"start_new_session": True}


def _kill(proc: subprocess.Popen) -> None:
   """!Kills a child and its process group.
   @param proc  the child
   @return None
   """
   try:
      if os.name == "nt":
         proc.kill()
      else:
         os.killpg(proc.pid, signal.SIGKILL)
   except (OSError, ProcessLookupError):
      pass


def build(project: BattleProject, rng: str = DEFAULT_RNG, cache: str | Path | None = None,
          progress: Progress | None = None, jobs: int | None = None) -> Path:
   """!Builds the bench (see Runner.build()).
   @param project   BattleProject
   @param rng       a generator name (generators())
   @param cache     the build folder (default cache_folder())
   @param progress  callback(phase, text), or None
   @param jobs      parallel compile jobs
   @return the bench executable
   """
   return Runner().build(project, rng, cache, progress, jobs)


def run(project: BattleProject, scenario: Document | Mapping[str, Any] | str | Path, rng: str | None = None,
        trace: Sequence[str] = (), progress: Progress | None = None, cache: str | Path | None = None,
        jobs: int | None = None) -> BenchRun:
   """!Builds the bench and runs a scenario (see Runner.build_and_run()).
   @param project   BattleProject
   @param scenario  Document, parsed scenario or file
   @param rng       a generator name (generators())
   @param trace     extra traces
   @param progress  callback(phase, text), or None
   @param cache     the build folder
   @param jobs      parallel compile jobs
   @return BenchRun
   """
   return Runner().build_and_run(project, scenario, rng, trace, progress, cache, jobs)   # rng None: the scenario's


def check(project: BattleProject, path: str | Path, rng: str | None = None, cache: str | Path | None = None,
          progress: Progress | None = None, jobs: int | None = None) -> list[str]:
   """!Runs a saved scenario and compares its transcript with its "expect" file (the engine's check_expected()).
   @param project   BattleProject
   @param path      the scenario file
   @param rng       the generator the expected transcript was made with, or None for the scenario's "rng"
   @param cache     the build folder
   @param progress  callback(phase, text), or None
   @param jobs      parallel compile jobs
   @return problems; empty when the transcript matches
   @throws BenchError when the scenario is malformed or names no "expect"
   """
   t = tool()
   data, _path = _scenario_data(path)
   rng = rng or scenario_rng(data)
   runner = Runner()
   exe = runner.build(project, rng, cache, progress, jobs)
   if progress is not None:
      progress(PHASE_RUN, "checking the transcript")
   try:
      if "result" in inspect.signature(t.check_expected).parameters:
         # E7: compare a run this runner made (cancellable) instead of running the bench again inside the tool
         return t.check_expected(None, path, result=runner.run(exe, data, (), rng).result)
      return t.check_expected(exe, path)
   except (t.BenchError, OSError) as e:
      raise BenchError(str(e)) from e


def scenario_rng(scenario: Mapping[str, Any]) -> str:
   """!The generator a scenario's expectations were made with (its "rng", E7), else DEFAULT_RNG.
   @param scenario  parsed scenario
   @return a generator name (one the game or the reference repo may not provide: build() says so)
   """
   rng = scenario.get("rng") if isinstance(scenario, Mapping) else None
   return rng if is_generator_name(rng) else DEFAULT_RNG
