"""![S6b] The world's cell interaction rules (engine C13b: world.json "interactions", capsule::map::Interaction): what
pressing Accept while facing a cell does when no object and no sign answers. The rules are tried in order and the
first that holds starts its script:

    "interactions": [{"behavior": NAME, "script": SCRIPT, "facing": DIRECTION, "vehicle": CLASS, "flag": FLAG,
                      "same_level": true, "after_actions": true}]

- behavior: the faced cell's behavior (one of the world's behaviors, the names maps paint);
- script: the script it starts (one of the world's scripts manifest);
- facing (optional, any when left out): the direction the player must face;
- vehicle (optional, any): the movement mode (vehicle class) the player must be in;
- flag (optional): a flag that must be set;
- same_level (optional): the faced cell's elevation level must be the player's;
- after_actions (optional): tried only after the field actions had nothing to do.

The engine's map compiler is the authority: every edit is checked by its compile_interactions() with the world's
behaviors and movement modes (names of scripts and flags only need to be names then, so a rule may name a script
written later), and problems() runs the very same function with the scripts manifest's names, as the build does.
Generic: nothing here knows what a game's behaviors mean. Qt-free; the World page's Interactions panel and
`capsule-studio interactions WORLD ...` use it.

Functions that change the world Document must be called inside doc.edit() (the panel's host.run_edit()).
"""
from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

from . import engine, events

if TYPE_CHECKING:
   from .document import Document
   from .world import Project

## A parsed JSON object.
JsonDict = dict[str, Any]

## The world's key of the rules (map_compiler KEYS "world").
RULES_KEY = "interactions"
## The world's behavior list (a world without one has the compiler's default: "normal" alone).
BEHAVIORS_KEY = "behaviors"
## The behaviors of a world that lists none (map_compiler.compile_world()'s default).
DEFAULT_BEHAVIORS = ("normal",)
## The keys a rule needs.
REQUIRED = ("behavior", "script")
## The conditions that name something (left out: any).
NAMED_CONDITIONS = ("facing", "vehicle", "flag")
## The conditions that are switches (left out: off).
SWITCHES = ("same_level", "after_actions")


def _mc() -> Any:
   """!The engine's map compiler.
   @return map_compiler
   """
   return engine.tool("map_compiler")


def keys() -> list[str]:
   """!A rule's keys as the engine's map compiler takes them (KEYS "interaction").
   @return the keys (behavior and script first)
   @throws AttributeError / KeyError for an engine before C13b
   """
   known = set(_mc().KEYS["interaction"])
   return list(REQUIRED) + [k for k in NAMED_CONDITIONS + SWITCHES if k in known] + \
      sorted(known - set(REQUIRED) - set(NAMED_CONDITIONS) - set(SWITCHES))


def max_rules() -> int:
   """!The most rules a world has (map_compiler.MAX_INTERACTIONS).
   @return the count
   """
   return int(_mc().MAX_INTERACTIONS)


def directions() -> list[str]:
   """!The directions a rule may ask the player to face (map_compiler.DIRECTIONS).
   @return down, up, left, right
   """
   return list(_mc().DIRECTIONS)


def behavior_names(world: Document) -> list[str]:
   """!The world's behaviors, in index order (the names a rule's behavior picks from).
   @param world  world Document
   @return names
   """
   raw = world.data.get(BEHAVIORS_KEY)
   if not isinstance(raw, list):
      return list(DEFAULT_BEHAVIORS)
   return [str(b.get("name")) for b in raw if isinstance(b, dict) and b.get("name")]


def vehicle_names(world: Document) -> list[str]:
   """!The world's movement modes (vehicle classes), in class order.
   @param world  world Document
   @return names
   """
   return [str(n) for n in _mc().vehicle_class_names(world.data) if n]


def rules(world: Document) -> list[JsonDict]:
   """!The world's rules, in the order they are tried.
   @param world  world Document
   @return the manifest's own list (empty when it has none)
   """
   raw = world.data.get(RULES_KEY)
   return raw if isinstance(raw, list) else []


class _AnyNames:
   """!Script and flag names an edit is checked with: any name is one (problems() checks them against the scripts)."""

   def __init__(self, error: type[Exception]) -> None:
      """!Takes the error the compiler expects.
      @param error  event_compiler.EventError
      """
      ## The error raised for a name that is no name.
      self.error = error

   def script(self, name: Any, where: str) -> int:
      """!A script's id (0: any name is one).
      @param name   the name
      @param where  location for messages
      @return 0
      """
      if not isinstance(name, str) or not name:
         raise self.error(f"{where}: a rule names its script")
      return 0

   def flag(self, name: Any, where: str) -> int:
      """!A flag's id (0: any name is one).
      @param name   the name
      @param where  location for messages
      @return 0
      """
      if not isinstance(name, str) or not name:
         raise self.error(f"{where}: flag names a flag")
      return 0


def compile_rules(world: Document, raw: list[JsonDict], names: Any = None) -> list[JsonDict]:
   """!The engine's compile_interactions() on rules for this world (its behaviors and movement modes).
   @param world  world Document
   @param raw    the rules
   @param names  event_compiler.Names (the scripts' names), or None to take any name
   @return the compiled rules
   @throws ValueError with the compiler's message when it refuses them
   """
   mc = _mc()
   evc = engine.tool("event_compiler")
   behaviors = {n: i for i, n in enumerate(behavior_names(world))}
   data = {RULES_KEY: raw}
   try:
      return mc.compile_interactions(data, behaviors, vehicle_names(world),
                                     names if names is not None else _AnyNames(evc.EventError))
   except mc.ManifestError as e:
      raise ValueError(str(e)) from None


def _clean(rule: JsonDict) -> JsonDict:
   """!A rule without the conditions that mean "any" (None, "", false), in the key order of keys().
   @param rule  the rule
   @return a new rule
   """
   out: JsonDict = {}
   for k in keys():
      v = rule.get(k)
      if k in SWITCHES:
         if v is True:
            out[k] = True
         elif v not in (None, False):
            out[k] = v   # not a switch value: the compiler says so
      elif v is not None and v != "":
         out[k] = v
   return out


def _store(world: Document, raw: list[JsonDict]) -> None:
   """!Checks rules with the compiler and keeps them (no rules: the key left out).
   @param world  world Document
   @param raw    the rules
   @return None
   """
   compile_rules(world, raw)
   if raw:
      world.data[RULES_KEY] = raw
   else:
      world.data.pop(RULES_KEY, None)


def add_rule(world: Document, behavior: str, script: str, index: int | None = None, **conditions: Any) -> int:
   """!Adds a rule (call inside world.edit()).
   @param world       world Document
   @param behavior    the faced cell's behavior
   @param script      the script it starts
   @param index       where in the order (None: last)
   @param conditions  facing, vehicle, flag, same_level, after_actions
   @return the rule's index
   """
   raw = copy.deepcopy(rules(world))
   at = len(raw) if index is None else max(0, min(index, len(raw)))
   raw.insert(at, _clean({"behavior": behavior, "script": script, **conditions}))
   _store(world, raw)
   return at


def set_rule(world: Document, index: int, **fields: Any) -> None:
   """!Changes a rule's fields (call inside world.edit()); None, "" or false removes a condition.
   @param world   world Document
   @param index   the rule
   @param fields  behavior, script, facing, vehicle, flag, same_level, after_actions
   @return None
   """
   raw = copy.deepcopy(rules(world))
   if not 0 <= index < len(raw):
      raise ValueError(f"no interaction rule {index}")
   unknown = set(fields) - set(keys())
   if unknown:
      raise ValueError(f"a rule has no {', '.join(sorted(unknown))} (its keys: {', '.join(keys())})")
   raw[index] = _clean({**raw[index], **fields})
   _store(world, raw)


def remove_rule(world: Document, index: int) -> None:
   """!Removes a rule (call inside world.edit()).
   @param world  world Document
   @param index  the rule
   @return None
   """
   raw = copy.deepcopy(rules(world))
   if not 0 <= index < len(raw):
      raise ValueError(f"no interaction rule {index}")
   del raw[index]
   _store(world, raw)


def move_rule(world: Document, index: int, delta: int) -> int:
   """!Moves a rule earlier (-1) or later (+1) in the order they are tried (call inside world.edit()).
   @param world  world Document
   @param index  the rule
   @param delta  -1 or +1
   @return its new index
   """
   raw = copy.deepcopy(rules(world))
   if not 0 <= index < len(raw):
      raise ValueError(f"no interaction rule {index}")
   to = max(0, min(index + delta, len(raw) - 1))
   raw.insert(to, raw.pop(index))
   _store(world, raw)
   return to


def script_names(project: Project) -> tuple[Any, str | None]:
   """!The scripts' names the build checks rules with (event_compiler.Names over the world's scripts manifest).
   @param project  Project
   @return (Names or None, a message when the scripts could not be read, or None)
   """
   evc = engine.tool("event_compiler")
   found = events.names(project)
   if found.get("error"):
      if events.scripts_path(project) is None:
         return evc.Names(None), None   # the compiler's own message: name the scripts manifest
      return None, f"scripts and flags not checked: {found['error']}"
   path = events.scripts_path(project)
   return evc.Names({n: i for i, n in enumerate(found["scripts"])}, {n: i for i, n in enumerate(found["flags"])},
                    source=str(path.name if path is not None else "")), None


def problems(project: Project) -> list[str]:
   """!What the build's map compiler refuses in the world's rules (its compile_interactions() with the scripts'
   names), and rules that can never run (an earlier rule takes every case they cover).
   @param project  Project
   @return problems ("error: ..." refused, "warning: ..." never runs or unchecked)
   """
   raw = rules(project.world)
   if not raw:
      return []
   names, note = script_names(project)
   out = [f"warning: {note}"] if note else []
   try:
      compile_rules(project.world, raw, names)
   except ValueError as e:
      out.append(f"error: {e}")
      return out
   for i, r in enumerate(raw):
      for j in range(i):
         if _covers(raw[j], r):
            out.append(f"warning: rule {i} ({r.get('behavior')} -> {r.get('script')}) never runs: rule {j} is tried "
                       "first and holds whenever it does")
            break
   return out


def _covers(earlier: JsonDict, later: JsonDict) -> bool:
   """!Whether an earlier rule holds whenever a later one does (same behavior, each of its conditions also the
   later's, and tried in the same pass: both before or both after the field actions).
   @param earlier  the earlier rule
   @param later    the later rule
   @return True when the later never runs
   """
   if earlier.get("behavior") != later.get("behavior"):
      return False
   if bool(earlier.get("after_actions")) != bool(later.get("after_actions")):
      return False
   for k in NAMED_CONDITIONS:
      if earlier.get(k) is not None and earlier.get(k) != later.get(k):
         return False
   return not earlier.get("same_level") or bool(later.get("same_level"))


def describe(rule: JsonDict) -> str:
   """!A rule as one line (the panel's list, the command line).
   @param rule  the rule
   @return e.g. "facing a 'counter' cell, facing up, on foot, flag F, same level, after actions -> Script"
   """
   parts = [f"facing a {rule.get('behavior')!r} cell"]
   if rule.get("facing"):
      parts.append(f"facing {rule['facing']}")
   if rule.get("vehicle"):
      parts.append(f"as {rule['vehicle']}")
   if rule.get("flag"):
      parts.append(f"flag {rule['flag']} set")
   if rule.get("same_level"):
      parts.append("same level")
   if rule.get("after_actions"):
      parts.append("after the field actions")
   return ", ".join(parts) + f" -> {rule.get('script')}"


def lines(world: Document) -> list[str]:
   """!The rules as text, in order.
   @param world  world Document
   @return lines
   """
   return [f"{i}: {describe(r)}" for i, r in enumerate(rules(world))]
