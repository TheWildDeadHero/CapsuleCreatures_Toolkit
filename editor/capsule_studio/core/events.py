"""!Map events (B-3): editing a map's warps (with their D-17 transitions),
triggers and signs, its area root, and the world's scripts manifest and
step hooks.

The engine's tools/event_compiler.py (through map_compiler.py) is the one
authority on what is valid: check() and diagnostics() run it on the open,
unsaved documents. This module adds what editors need: records by kind and
index, changes as one undo step each, warp numbers kept right when a warp is
removed, and the names (scripts, flags, variables) the scripts manifest
offers. Qt-free; the events panel, its map tool and `capsule-studio events`
use it.

Functions that change one Document must be called inside doc.edit() (the
host's run_edit()); remove_event() may change several documents and makes
its own undo steps, so call it outside one.

Event records are the manifest's own objects: {"at": [x, y], "elevation",
...}; see the engine's event_compiler.py for every key.

I3: warps fire by "step", "press", "arrow" (a press facing the direction),
"door" (from the neighbouring cell, facing it) or "none" (a landing only,
kept so warp numbers stay the source's), and land at "to": a map, or
"dynamic" (the game decides when it fires). A map's "unpainted_events" lets
its events and objects stand on unpainted cells (set_unpainted_events()).

S4 (engine C10): a coord trigger's "run": "step" (the default, left out) or "immediate" (trigger_runs(): the
script runs to its end at once, no lock, the walker keeps going and the cell's next events are checked); the
engine refuses an immediate trigger whose script may wait, which immediate_problem() says with a way out
(names()["waiting"]: the scripts that may wait).
"""
from __future__ import annotations

import copy
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import engine, paths
from .document import Document, DocumentError

if TYPE_CHECKING:
   from ..plugins.registry import Diagnostic
   from .world import Project

## Event lists in a map's "events", in display order, with their singular names.
KINDS = {"warps": "warp", "triggers": "trigger", "signs": "sign"}
## Directions (field::Direction order).
DIRECTIONS = ["down", "up", "left", "right"]
## Warp transitions (capsule::script::Transition order, D-17); a warp without one uses the world's.
TRANSITIONS = ["none", "fade", "white", "mosaic", "wipe_h", "wipe_v", "box"]
## Keys each kind may hold (besides "at").
FIELDS = {
   "warps": ("elevation", "to", "warp", "trigger", "direction", "transition", "door"),   # S3: door (D-30)
   "triggers": ("elevation", "script", "var", "value", "run"),   # S4: run (engine C10)
   "signs": ("elevation", "script", "facing", "flag"),
}
## S3: a warp's door binding names a door asset key (D-30, event_compiler: "door:NAME").
DOOR_PREFIX = "door:"
## Warp triggers that take a direction (I3: the engine's event_compiler.WARP_TRIGGERS step and none take none).
DIRECTED = ("press", "arrow", "door")
## The default warp trigger (left out of the manifest).
STEP = "step"
## S4 (engine C10): how a coord trigger runs when the engine predates event_compiler.TRIGGER_RUNS: "step" (the
## default, left out of the map) locks the walker and runs the script; "immediate" runs it to its end at once.
DEFAULT_TRIGGER_RUNS = ("step",)
## S4: the place of "immediate" in event_compiler.TRIGGER_RUNS (after the default "step").
IMMEDIATE_RUN = 1
## Unit steps per direction: the cell a door warp is fired from is the one opposite its direction.
STEPS = {"down": (0, 1), "up": (0, -1), "left": (-1, 0), "right": (1, 0)}
## Highest elevation an event may name (the attribute cell's elevation field, core.maps.FIELDS; 0 is any level).
MAX_ELEVATION = 15
## Longest step hook period, in steps (a power of two).
MAX_HOOK_PERIOD = 32768
## Coordinates in an event's "at": [x, y].
AT_LENGTH = 2

## A parsed JSON object (an event record, a step hook, a manifest).
JsonDict = dict[str, Any]
## An event with where it is listed: (plural kind, index in that list, the event).
EventRow = tuple[str, int, JsonDict]


def trigger_runs() -> list[str]:
   """!S4: how a trigger may run (the engine's event_compiler.TRIGGER_RUNS: step, immediate), the default first.
   @return words
   """
   try:
      return [str(r) for r in getattr(engine.tool("event_compiler"), "TRIGGER_RUNS", DEFAULT_TRIGGER_RUNS)]
   except engine.EngineNotFound:
      return list(DEFAULT_TRIGGER_RUNS)


def immediate_problem(e: JsonDict, waiting: Iterable[str]) -> str | None:
   """!S4 (engine C10): why the engine refuses an immediate trigger: its script may wait (a message, a delay, a walk:
   an immediate trigger runs it to its end at once, event_compiler's rule on the script compiler's "waits").
   @param e        the trigger
   @param waiting  the scripts that may wait (names()["waiting"])
   @return the message, or None
   """
   runs = trigger_runs()
   if len(runs) <= IMMEDIATE_RUN or e.get("run", runs[0]) != runs[IMMEDIATE_RUN]:
      return None
   script = e.get("script")
   if script in set(waiting):
      return f"{script} may wait (a message, a delay, a walk...); an immediate trigger runs its script to its end at " \
             "once: run it on step, or move the waiting part to a script it starts"
   return None


def warp_triggers() -> list[str]:
   """!What fires a warp (the engine's event_compiler.WARP_TRIGGERS; I3: arrow, door, none).
   @return trigger words
   """
   return list(engine.tool("event_compiler").WARP_TRIGGERS)


def dynamic_to() -> str:
   """!The "to" of a warp whose destination the game decides (the engine's event_compiler.DYNAMIC_TO; I3).
   @return "dynamic"
   """
   return str(engine.tool("event_compiler").DYNAMIC_TO)


def door_cell(e: JsonDict) -> tuple[int, int] | None:
   """!The cell a door warp is fired from: the neighbour on the side opposite its direction (I3).
   @param e  the warp
   @return (x, y), or None for another warp
   """
   at = e.get("at")
   if e.get("trigger") != "door" or e.get("direction") not in STEPS or not (isinstance(at, list) and
                                                                            len(at) == AT_LENGTH):
      return None
   dx, dy = STEPS[e["direction"]]
   return at[0] - dx, at[1] - dy


def set_unpainted_events(doc: Document, on: bool) -> None:
   """!Whether a map's warps, triggers and objects may stand on unpainted cells (I3 "unpainted_events": imported
   data kept as its source has it; the walker never steps onto such a cell by itself). Call inside doc.edit().
   @param doc  map Document
   @param on   True or False
   @return None
   """
   if on:
      doc.data["unpainted_events"] = True
   else:
      doc.data.pop("unpainted_events", None)


def _kind(kind: str) -> str:
   """!Checks a kind name.
   @param kind  'warps', 'triggers' or 'signs' (singular accepted)
   @return the plural key
   """
   for plural, singular in KINDS.items():
      if kind in (plural, singular):
         return plural
   raise DocumentError(f"unknown event kind {kind!r} (warp, trigger or sign)")


def events(doc: Document, kind: str) -> list[JsonDict]:
   """!A map's events of one kind.
   @param doc   map Document
   @param kind  event kind
   @return list of event objects (the document's own; do not change them outside edit())
   """
   ev = doc.data.get("events") or {}
   items = ev.get(_kind(kind)) if isinstance(ev, dict) else None
   return items if isinstance(items, list) else []


def all_events(doc: Document) -> list[EventRow]:
   """!Every event of a map.
   @param doc  map Document
   @return list of (kind, index, event)
   """
   return [(k, i, e) for k in KINDS for i, e in enumerate(events(doc, k))]


def events_at(doc: Document, x: int, y: int) -> list[EventRow]:
   """!The events on a cell.
   @param doc  map Document
   @param x    column
   @param y    row
   @return list of (kind, index, event)
   """
   return [(k, i, e) for k, i, e in all_events(doc) if e.get("at") == [x, y]]


def describe(kind: str, e: JsonDict) -> str:
   """!One line about an event.
   @param kind  event kind
   @param e     the event
   @return text
   """
   kind = _kind(kind)
   elev = f" (level {e['elevation']})" if e.get("elevation") else ""
   if kind == "warps":
      trig = e.get("trigger", STEP)
      how = f", {trig} {e.get('direction')}" if trig in DIRECTED else ", a landing only" if trig == "none" else ""
      trans = f", {e['transition']}" if "transition" in e else ""
      trans += f", door {e['door']}" if "door" in e else ""   # S3 (D-30)
      dest = f"a destination the game decides (warp {e.get('warp', 0)})" if e.get("to") == dynamic_to() else \
         f"{e.get('to')} #{e.get('warp', 0)}"
      return f"warp to {dest}{how}{trans}{elev}"
   if kind == "triggers":
      cond = f" while {e['var']} == {e.get('value', 0)}" if "var" in e else ""
      runs = f", runs at once ({e['run']})" if e.get("run", STEP) != STEP else ""   # S4 (C10)
      return f"trigger: {e.get('script')}{cond}{runs}{elev}"
   facing = f", facing {e['facing']}" if e.get("facing", "any") != "any" else ""
   flag = f", until {e['flag']}" if "flag" in e else ""
   return f"sign: {e.get('script')}{facing}{flag}{elev}"


def _clean(kind: str, fields: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
   """!Checks field names and drops None values.
   @param kind    plural kind
   @param fields  {key: value or None}
   @return (fields to set, names of fields to remove)
   """
   bad = sorted(set(fields) - set(FIELDS[kind]))
   if bad:
      raise DocumentError(f"a {KINDS[kind]} has no field(s) {', '.join(bad)} (known: {', '.join(FIELDS[kind])})")
   keep = {k: v for k, v in fields.items() if v is not None}
   drop = [k for k, v in fields.items() if v is None]
   if "elevation" in keep and (not isinstance(keep["elevation"], int)
                               or not 0 <= keep["elevation"] <= MAX_ELEVATION):
      raise DocumentError(f"elevation is 0 (any level) to {MAX_ELEVATION}")
   # Elevation 0 (any level) is the default, so it is not written.
   if keep.get("elevation") == 0:
      del keep["elevation"]
      drop.append("elevation")
   if "transition" in keep and keep["transition"] not in TRANSITIONS:
      raise DocumentError(f"transition is one of {', '.join(TRANSITIONS)} (none given: the world's default)")
   if kind == "warps" and "trigger" in keep and keep["trigger"] not in warp_triggers():
      raise DocumentError(f"trigger is one of {', '.join(warp_triggers())}")
   if "direction" in keep and keep["direction"] not in DIRECTIONS:
      raise DocumentError(f"direction is one of {', '.join(DIRECTIONS)}")
   if "run" in keep and keep["run"] not in trigger_runs():   # S4: event_compiler's TRIGGER_RUNS
      raise DocumentError(f"run is one of {', '.join(trigger_runs())}")
   if keep.get("run") == STEP:   # the default is not written
      del keep["run"]
      drop.append("run")
   if "door" in keep and (not isinstance(keep["door"], str) or not keep["door"].startswith(DOOR_PREFIX)):
      raise DocumentError(f"a warp's door names a door asset ({DOOR_PREFIX}NAME)")   # S3: event_compiler's rule
   return keep, drop


def add_event(doc: Document, kind: str, x: int, y: int, **fields: Any) -> int:
   """!Adds an event (call inside doc.edit()).
   @param doc     map Document
   @param kind    event kind
   @param x       column
   @param y       row
   @param fields  its fields (see FIELDS)
   @return its index
   """
   kind = _kind(kind)
   keep, _drop = _clean(kind, fields)
   ev = doc.data.setdefault("events", {})
   if not isinstance(ev, dict):
      raise DocumentError('"events" must be an object; fix the map file by hand')
   items = ev.setdefault(kind, [])
   items.append(dict({"at": [int(x), int(y)]}, **keep))
   return len(items) - 1


def set_event(doc: Document, kind: str, index: int, **fields: Any) -> None:
   """!Changes an event's fields; None removes one (call inside doc.edit()).
   @param doc     map Document
   @param kind    event kind
   @param index   its index
   @param fields  fields to change
   @return None
   """
   kind = _kind(kind)
   items = events(doc, kind)
   if not 0 <= index < len(items):
      raise DocumentError(f"no {KINDS[kind]} {index}")
   keep, drop = _clean(kind, fields)
   e = doc.data["events"][kind][index]
   e.update(keep)
   for k in drop:
      e.pop(k, None)
   # Fields that only mean something with another: a step warp (or I3's landing-only "none") has no direction,
   # a trigger without a variable has no value.
   if kind == "warps" and e.get("trigger", STEP) not in DIRECTED:
      e.pop("direction", None)
      if e.get("trigger", STEP) == STEP:
         e.pop("trigger", None)
   if kind == "triggers" and "var" not in e:
      e.pop("value", None)


def move_event(doc: Document, kind: str, index: int, x: int, y: int) -> None:
   """!Moves an event to another cell (call inside doc.edit()).
   @param doc    map Document
   @param kind   event kind
   @param index  its index
   @param x      column
   @param y      row
   @return None
   """
   kind = _kind(kind)
   if not 0 <= index < len(events(doc, kind)):
      raise DocumentError(f"no {KINDS[kind]} {index}")
   doc.data["events"][kind][index]["at"] = [int(x), int(y)]


def warp_referrers(project: Project, map_name: str, index: int) -> list[tuple[str, int]]:
   """!The warps of the world that land on a warp.
   @param project   Project
   @param map_name  map of the warp
   @param index     its number
   @return list of (map name, warp index)
   """
   out = []
   for n in project.map_names():
      for i, w in enumerate(events(project.map(n), "warps")):
         if w.get("to") == map_name and w.get("warp", 0) == index:
            out.append((n, i))
   return out


def remove_event(project: Project, map_name: str, kind: str, index: int) -> None:
   """!Removes an event (one undo step; call it outside doc.edit()).
   Removing a warp renumbers the warps after it, and the map's own warps that
   land on one of them follow in the same step. It is refused while a warp
   lands on it, or while a warp of another map lands on a later warp of
   this map (renumbering two files could not be undone as one step).
   @param project   Project
   @param map_name  the map
   @param kind      event kind
   @param index     its index
   @return None
   """
   kind = _kind(kind)
   doc = project.map(map_name)
   items = events(doc, kind)
   if not 0 <= index < len(items):
      raise DocumentError(f"no {KINDS[kind]} {index}")
   if kind == "warps":
      refs = [r for r in warp_referrers(project, map_name, index) if r != (map_name, index)]
      if refs:
         where = ", ".join(f"{n} warp {i}" for n, i in refs)
         raise DocumentError(f"{map_name} warp {index} is where {where} land(s); point them elsewhere first")
      # Warps of other maps landing after the removed one (their numbers would shift).
      outside = [(n, i) for n in project.map_names() if n != map_name
                 for i, w in enumerate(events(project.map(n), "warps"))
                 if w.get("to") == map_name and isinstance(w.get("warp", 0), int) and w.get("warp", 0) > index]
      if outside:
         where = ", ".join(f"{n} warp {i}" for n, i in outside)
         raise DocumentError(f"{where} land(s) on later warps of {map_name}, whose numbers would change; "
                             "remove the map's last warps first, or point them elsewhere")
   with doc.edit(f"Remove {KINDS[kind]}") as data:
      del data["events"][kind][index]
      if kind == "warps":
         # The map's own warps landing after the removed one follow the renumbering.
         for w in data["events"].get("warps", []):
            if w.get("to") == map_name and isinstance(w.get("warp", 0), int) and w.get("warp", 0) > index:
               w["warp"] -= 1
      if not any(data["events"].get(k) for k in KINDS):
         del data["events"]


def area(doc: Document, map_name: str) -> str:
   """!A map's area root.
   @param doc       map Document
   @param map_name  its name
   @return the area map's name (its own name when not set)
   """
   return doc.data.get("area", map_name)


def set_area(doc: Document, map_name: str, root: str | None) -> None:
   """!Sets a map's area root (B-2): the outdoor map whose area it is in (call inside doc.edit()).
   @param doc       map Document
   @param map_name  its name
   @param root      area map name, or None / its own name for its own area
   @return None
   """
   if root is None or root == map_name:
      doc.data.pop("area", None)
   else:
      doc.data["area"] = root


def scripts_path(project: Project) -> Path | None:
   """!The scripts manifest events name things from: the world's "scripts",
   else the one its game's reference/project.json names (the build passes
   that one to the map compiler).
   @param project  Project
   @return resolved Path, or None
   """
   rel = project.world.data.get("scripts")
   if isinstance(rel, str) and rel:
      return (project.base / rel).resolve()
   return game_scripts_path(project)


def game_scripts_path(project: Project) -> Path | None:
   """!The scripts manifest the world's game names (project.json "scripts").
   @param project  Project
   @return resolved Path, or None
   """
   from ..plugins.project import find_project
   import json
   manifest, folder = find_project(project.world.path)
   if manifest is None:
      return None
   try:
      rel = json.loads(Path(manifest).read_text(encoding="utf-8")).get("scripts")
   except (OSError, ValueError):
      return None
   return (Path(folder) / rel).resolve() if isinstance(rel, str) and rel else None


def set_scripts(project: Project, path: str | Path | None) -> None:
   """!Names the world's scripts manifest (stored relative to the world; call inside project.world.edit()).
   @param project  Project
   @param path     scripts.json, or None to remove
   @return None
   """
   data = project.world.data
   if path is None:
      data.pop("scripts", None)
      return
   p = Path(path)
   data["scripts"] = paths.relative(p, project.base) if paths.is_absolute_text(str(p)) else p.as_posix()


def names(project: Project) -> dict[str, Any]:
   """!What events may name: scripts, flags and variables of the world's scripts manifest.
   @param project  Project
   @return dict scripts (list), flags (list), vars ({name: (lo, hi)}), error (str or None)
   """
   out = {"scripts": [], "flags": [], "vars": {}, "error": None, "waiting": []}
   path = scripts_path(project)
   if path is None:
      out["error"] = "the world names no scripts manifest"
      return out
   # I2: compiled again only when a file of the scripts' folder, or the world on disk (the script compiler reads the
   # world and its maps' files for their names), changed: a large game's scripts take a second
   key = (str(path), project.scripts_times(path), project.disk_times())
   if project.names_cache is not None and project.names_cache[0] == key:
      return copy.deepcopy(project.names_cache[1])
   out = _names(path, out)
   project.names_cache = (key, copy.deepcopy(out))
   return out


def _names(path: Path, out: dict[str, Any]) -> dict[str, Any]:
   """!Compiles the scripts manifest for names() (no cache).
   @param path  the scripts manifest
   @param out   the result to fill
   @return out
   """
   try:
      comp = engine.tool("script_compiler").compile_file(path)
   except (OSError, ValueError) as e:
      out["error"] = f"cannot read {path.name}: {e}"
      return out
   if comp.errors():
      out["error"] = f"{path.name} does not compile: {comp.errors()[0]}"
      return out
   out["scripts"] = list(comp.order["script"])
   out["flags"] = list(comp.order["flag"])
   out["vars"] = {n: (comp.vars[n]["lo"], comp.vars[n]["hi"]) for n in comp.order["var"]}
   # S4 (C10): the scripts that may wait (directly or through calls): an immediate trigger may not run one
   out["waiting"] = sorted(n for n, w in comp.result.get("waits", {}).items() if w)
   return out


def step_hooks(project: Project) -> list[JsonDict]:
   """!The world's step hooks.
   @param project  Project
   @return list of hook objects (name, period, phase)
   """
   hooks = project.world.data.get("step_hooks")
   return hooks if isinstance(hooks, list) else []


def add_hook(project: Project, name: str, period: int, phase: int | None = None) -> None:
   """!Adds a step hook (call inside project.world.edit()).
   @param project  Project
   @param name     identifier
   @param period   a power of two, 1-32768
   @param phase    0 to period - 1, or None to let the compiler spread it
   @return None
   """
   if not isinstance(name, str) or not name.isidentifier():
      raise DocumentError(f"{name!r} is not an identifier")
   if any(h.get("name") == name for h in step_hooks(project)):
      raise DocumentError(f"step hook {name!r} exists already")
   # A power of two has one bit set, so clearing its lowest set bit (p & (p - 1)) leaves 0.
   if not isinstance(period, int) or not 1 <= period <= MAX_HOOK_PERIOD or period & (period - 1):
      raise DocumentError(f"period must be a power of two, 1-{MAX_HOOK_PERIOD}")
   if phase is not None and not 0 <= phase < period:
      raise DocumentError(f"phase must be 0-{period - 1}")
   hook = {"name": name, "period": period}
   if phase is not None:
      hook["phase"] = phase
   project.world.data.setdefault("step_hooks", []).append(hook)


def remove_hook(project: Project, name: str) -> None:
   """!Removes a step hook (call inside project.world.edit()). Hook IDs after it shift down.
   @param project  Project
   @param name     hook name
   @return None
   """
   hooks = step_hooks(project)
   i = next((i for i, h in enumerate(hooks) if h.get("name") == name), None)
   if i is None:
      raise DocumentError(f"no step hook {name!r}")
   data = project.world.data
   del data["step_hooks"][i]
   if not data["step_hooks"]:
      del data["step_hooks"]


def check(project: Project) -> str | None:
   """!Compiles every map's events with the engine's rules, on the open documents.
   @param project  Project
   @return error message, or None when they compile
   """
   # I2: Project.check_events() compiles again only when what the event compilers read changed
   return project.check_events(game_scripts_path(project))


def diagnostics(project: Project, name: str | None = None) -> list[Diagnostic]:
   """!Event problems: what the build would reject, and events on cells the
   walker can never stand on.
   @param project  Project
   @param name     only this map, or None for all
   @return list of plugins.Diagnostic
   """
   from ..plugins.registry import Diagnostic
   from . import maps
   out = []
   error = check(project)
   if error:
      out.append(Diagnostic("error", error, name))
   waiting = names(project).get("waiting", [])
   for n in [name] if name else project.map_names():
      doc = project.map(n)
      for kind in ("warps", "triggers"):
         for i, e in enumerate(events(doc, kind)):
            at = e.get("at")
            if not (isinstance(at, list) and len(at) == AT_LENGTH):
               continue
            cell = maps.get(doc.data, at[0], at[1])
            # I3: a door is fired from its neighbour, and a landing only is never fired: they may be blocked
            fired_on_it = kind != "warps" or e.get("trigger", STEP) in (STEP, "press", "arrow")
            if fired_on_it and cell is not None and maps.unpack(cell)["collision"]:
               out.append(Diagnostic("warning", f"map {n}: {KINDS[kind]} {i} is on a cell with collision; the "
                                                "walker can never arrive there", n, tuple(at)))
            problem = immediate_problem(e, waiting) if kind == "triggers" else None
            if problem is not None:   # S4: said here with a way out (the engine's check refuses it too)
               out.append(Diagnostic("error", f"map {n}: trigger {i}: {problem}", n, tuple(at)))
            front = door_cell(e) if kind == "warps" else None
            if front is not None:   # I3: the walker stands there, facing the door, to open it
               fc = maps.get(doc.data, *front)
               if fc is None or maps.unpack(fc)["collision"]:
                  out.append(Diagnostic("warning", f"map {n}: door warp {i} is opened from {front[0]}, {front[1]}, "
                                                   "which the walker cannot stand on", n, tuple(at)))
   return out
