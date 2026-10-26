"""!The ruleset's pipelines and points (D-20 D, capsule.ruleset/2): the step
lists the engine runs for damage, self_hit, speed, accuracy, crit and
effect_odds, and the modifier points their "point" steps run, as editing helpers over the ruleset
Document; their analysed ranges; and a damage trace that runs the damage
pipeline as the engine does.

    "points":    {"power": {"holder": "user", "sources": ["passive", "item"], "range": [1, 1023]}, ...},
    "pipelines": {"damage": [{"let": "attack", "expr": "staged(offense_raw, offense_stage)",
                              "range": [1, "STAT_CAP"]},
                             {"point": "offense", "on": "attack"},
                             {"roll": "r", "span": "16"}, ...], ...}

A step is one of {"let": var, "expr": text, "range": [lo, hi]} (range
optional), {"point": name, "on": var} or {"roll": var, "span": text}. Every
pipeline must exist and set its outputs, but for the optional ones
(ruleset_compiler.OPTIONAL_PIPELINES: effect_odds, E9), which a ruleset may
leave out and then gets the engine's default steps (the plain odds): the
studio shows those as "engine default (plain odds)" (is_engine_default(),
default_note()), and the first edit starts from them. The engine's ruleset compiler
checks the rest (names, ranges, int32 safety) on every compile, and its
interval analysis gives each step's range (pipeline_report()).

damage_trace() rebuilds what the engine's battle::damage_preview() does: the
decisive type tiers, then the damage pipeline with the battle compiler's
point_runner() running the point handlers, step by step
(ruleset_compiler.run_pipeline()).

Editing helpers change the ruleset Document; call them inside
ruleset.edit(). Nothing here depends on a user interface.
"""
from __future__ import annotations

import copy
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from . import battle, engine, logic
from .document import Document, DocumentError
from .structure import record

if TYPE_CHECKING:
   from .battle import BattleProject

## A parsed JSON object.
JsonDict = dict[str, Any]
## One analysed step (pipeline_report()): index, kind, var, text, bounds, analysed, range (or None), clamp_active.
StepRow = dict[str, Any]
## One traced step: (index, kind, variable, value before (point steps; else None), value after, step text).
TraceStep = tuple[int, str, str, "int | None", int, str]

## The ruleset's pipelines object.
PIPELINES_KEY = "pipelines"
## The ruleset's points object.
POINTS_KEY = "points"
## Step kinds, by the key that names them.
STEP_KINDS = ("let", "point", "roll")
## The keys of each step kind.
STEP_KEYS = {"let": ("let", "expr", "range"), "point": ("point", "on"), "roll": ("roll", "span")}
## Keys of a point.
POINT_KEYS = ("holder", "sources", "range")
## Holder of a new point.
DEFAULT_HOLDER = "user"
## Numbers in a range ([lo, hi]).
RANGE_LEN = 2
## Percent: an HP share of 100 is full health.
PERCENT = 100
## Battlers active on a battler's side in a preview (a single battle; damage_trace() takes others).
SIDE_ACTIVE = 1
## Level damage_trace() uses when none is given.
DEFAULT_LEVEL = 50
## The pipeline damage_trace() runs.
DAMAGE = "damage"
## Index of the "no damage" kind in the engine's decisive tier kinds (bc.DECISIVE: zero, then ko).
ZERO_DECISIVE = 0
## Engine index of the first status / item of the manifest lists (0 is "none"; battlec/pipelines.py FIRST_LISTED).
FIRST_LISTED = 1
## Most references a refused removal lists.
REFERENCES_SHOWN = 6
## What each optional pipeline's engine default does, as the studio names it ("engine default (plain odds)").
DEFAULT_NOTES = {"effect_odds": "plain odds", "ai_score": "adds nothing"}   # ai_score: G1
## Name of an optional pipeline's default steps when DEFAULT_NOTES has no word for it.
DEFAULT_STEPS_NOTE = "the engine's steps"


## The speed pipeline's input naming the stage its stage_scale() reads (ruleset_compiler.INPUT_DEFAULTS).
SPEED_STAGE_ID = "speed_stage_id"
## What the engine does with its reserved point move_type (ruleset_compiler.MOVE_TYPE_POINT, E13b), shown by the
## points editor and `point list`.
MOVE_TYPE_NOTE = ("reserved name: the engine runs this point on a move's type before each hit's chart and "
                  "same-type checks (move.type then reads the hit's type); a value that names no type keeps the "
                  "move's own. Its handlers are typically the move's own (source move).")

def _rc() -> Any:
   """!The engine's ruleset compiler.
   @return module
   """
   return engine.tool("ruleset_compiler")


def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


def handler_owners() -> dict[str, str]:
   """!The point source kind of each battle manifest list whose entries may hold point handlers (the engine's
   OWNER_SOURCES, battle_compiler's re-export: a point's "sources" name these kinds, alone or as user.KIND /
   target.KIND; E13b: moves, volatiles and side conditions besides passives, items, statuses and weathers).
   @return {manifest list: source kind}
   """
   return dict(_bc().OWNER_SOURCES)


def reserved_points() -> dict[str, str]:
   """!The point names the engine itself runs outside the pipelines' point steps, with what it does with them
   (E13b: ruleset_compiler.MOVE_TYPE_POINT, the hit's type).
   @return {point name: note}
   """
   return {_rc().MOVE_TYPE_POINT: MOVE_TYPE_NOTE}


# -- pipelines --------------------------------------------------------------------------------------------------------

def pipeline_names() -> list[str]:
   """!The pipelines the engine runs, in its order.
   @return names (damage, self_hit, speed, accuracy, crit, effect_odds, ai_score)
   """
   return list(_rc().PIPELINES)


def optional_pipelines() -> dict[str, list[JsonDict]]:
   """!The pipelines a ruleset may leave out, with the steps the engine then runs (ruleset_compiler
   OPTIONAL_PIPELINES).
   @return {name: default steps} (copies)
   """
   return copy.deepcopy(dict(_rc().OPTIONAL_PIPELINES))


def is_engine_default(doc: Document, name: str) -> bool:
   """!Whether the ruleset leaves an optional pipeline out (the engine runs its default steps).
   @param doc   ruleset Document
   @param name  pipeline name
   @return True for an optional pipeline the ruleset does not list
   """
   _check_pipeline(name)
   given = doc.data.get(PIPELINES_KEY)
   return name in _rc().OPTIONAL_PIPELINES and not (isinstance(given, dict) and name in given)


def default_note(name: str) -> str:
   """!How the studio names an optional pipeline's engine default.
   @param name  pipeline name
   @return e.g. "engine default (plain odds)"
   """
   from .battle import ENGINE_DEFAULT   # local, as BattleProject is: core.battle imports core.logic

   return f"{ENGINE_DEFAULT} ({DEFAULT_NOTES.get(name, DEFAULT_STEPS_NOTE)})"


def shown_steps(doc: Document, name: str) -> list[JsonDict]:
   """!The steps the engine runs for a pipeline: the ruleset's, or an optional pipeline's default steps.
   @param doc   ruleset Document
   @param name  pipeline name
   @return the live list when the ruleset lists the pipeline, else a copy of the defaults ([] for a missing
           pipeline that is not optional)
   """
   _check_pipeline(name)
   given = doc.data.get(PIPELINES_KEY)
   lst = given.get(name) if isinstance(given, dict) else None
   if isinstance(lst, list):
      return lst
   return optional_pipelines().get(name, [])


def reset_pipeline(doc: Document, name: str) -> bool:
   """!Gives an optional pipeline back to the engine (the ruleset leaves it out).
   @param doc   ruleset Document
   @param name  an optional pipeline
   @return True when the ruleset listed it
   @throws DocumentError for a pipeline every ruleset must list
   """
   _check_pipeline(name)
   if name not in _rc().OPTIONAL_PIPELINES:
      raise DocumentError(f"{name} has no engine default: every ruleset lists it")
   given = doc.data.get(PIPELINES_KEY)
   if not isinstance(given, dict) or name not in given:
      return False
   del given[name]
   return True


def _check_pipeline(name: str) -> None:
   """!Refuses a pipeline name the engine does not run.
   @param name  pipeline name
   @return None
   @throws DocumentError when it is unknown
   """
   if name not in _rc().PIPELINES:
      raise DocumentError(f"unknown pipeline {name!r} (pipelines: {', '.join(pipeline_names())})")


def pipeline_inputs(name: str) -> list[str]:
   """!The inputs the engine passes a pipeline (its fixed contract).
   @param name  pipeline name
   @return input names
   """
   _check_pipeline(name)
   return list(_rc().PIPELINES[name]["inputs"])


def pipeline_outputs(name: str) -> list[str]:
   """!The variables a pipeline must set (the first is its result).
   @param name  pipeline name
   @return output names
   """
   _check_pipeline(name)
   return list(_rc().PIPELINES[name]["outputs"])


def steps(doc: Document, name: str) -> list[JsonDict]:
   """!A pipeline's steps.
   @param doc   ruleset Document
   @param name  pipeline name
   @return the list (live; created when absent, an optional pipeline from the engine's default steps; change it
           only inside doc.edit())
   """
   _check_pipeline(name)
   pl = doc.data.get(PIPELINES_KEY)
   if not isinstance(pl, dict):
      pl = doc.data[PIPELINES_KEY] = {}
   if not isinstance(pl.get(name), list):
      pl[name] = optional_pipelines().get(name, [])
   return pl[name]


def step_kind(step: Any) -> str:
   """!Which kind a step is.
   @param step  step dict
   @return "let", "point" or "roll"
   @throws DocumentError when it is none (or several) of them
   """
   kinds = [k for k in STEP_KINDS if isinstance(step, dict) and k in step]
   if len(kinds) != 1:
      raise DocumentError("a step is {\"let\", \"expr\", \"range\"}, {\"point\", \"on\"} or {\"roll\", \"span\"}")
   return kinds[0]


def step_text(step: JsonDict) -> str:
   """!A step in words.
   @param step  step dict
   @return e.g. "let d = max(d, 1) [1, 65535]", "point power on power", "roll r in [0, ROLL_SPAN)"
   """
   kind = step_kind(step)
   if kind == "point":
      return f"point {step['point']} on {step.get('on')}"
   if kind == "roll":
      return f"roll {step['roll']} in [0, {step.get('span')})"
   rng = step.get("range")
   return f"let {step['let']} = {step.get('expr')}" + (f" [{rng[0]}, {rng[1]}]" if isinstance(rng, list) else "")


def _range(value: Any) -> list[Any]:
   """!A [lo, hi] range: integers or constant names (STAT_CAP).
   @param value  the value
   @return the list
   @throws DocumentError when it is not one
   """
   if not isinstance(value, (list, tuple)) or len(value) != RANGE_LEN or \
         not all(isinstance(v, (int, str)) and not isinstance(v, bool) for v in value):
      raise DocumentError("a range is [lo, hi] (integers or constant names)")
   return [v if isinstance(v, str) else int(v) for v in value]


def make_step(kind: str, var: str, text: str | None = None, rng: list[Any] | None = None) -> JsonDict:
   """!A new step.
   @param kind  "let", "point" or "roll"
   @param var   the variable it sets (let, roll) or runs the point on (point)
   @param text  the expression (let), the point's name (point) or the span (roll)
   @param rng   a let's clamp range, or None
   @return the step dict
   """
   if kind not in STEP_KINDS:
      raise DocumentError(f"a step kind is one of {', '.join(STEP_KINDS)}")
   if not isinstance(var, str) or not var.strip() or not isinstance(text, str) or not text.strip():
      raise DocumentError(f"a {kind} step needs a variable and " +
                          {"let": "an expression", "point": "a point", "roll": "a span"}[kind])
   if kind == "point":
      return {"point": text.strip(), "on": var.strip()}
   if kind == "roll":
      return {"roll": var.strip(), "span": text.strip()}
   step = {"let": var.strip(), "expr": text.strip()}
   if rng is not None:
      step["range"] = _range(rng)
   return step


def _index(lst: list[Any], index: int, what: str) -> int:
   """!A list index, checked.
   @param lst    the list
   @param index  wanted index
   @param what   what the list is (messages)
   @return the index
   @throws DocumentError when it is outside the list
   """
   if not isinstance(index, int) or not 0 <= index < len(lst):
      raise DocumentError(f"{what} has no step {index} (steps 0 to {len(lst) - 1})" if lst else f"{what} is empty")
   return index


def add_step(doc: Document, pipeline: str, step: JsonDict, index: int | None = None) -> int:
   """!Inserts a step.
   @param doc       ruleset Document
   @param pipeline  pipeline name
   @param step      step dict (make_step())
   @param index     position, or None for the end
   @return its index
   """
   step_kind(step)
   lst = steps(doc, pipeline)
   at = len(lst) if index is None else max(0, min(len(lst), int(index)))
   lst.insert(at, copy.deepcopy(step))
   return at


def remove_step(doc: Document, pipeline: str, index: int) -> JsonDict:
   """!Removes a step.
   @param doc       ruleset Document
   @param pipeline  pipeline name
   @param index     step index
   @return the removed step
   """
   lst = steps(doc, pipeline)
   return lst.pop(_index(lst, index, f"pipeline {pipeline}"))


def move_step(doc: Document, pipeline: str, index: int, delta: int) -> bool:
   """!Moves a step up or down (the order is the order the engine runs them, and of the RNG draws).
   @param doc       ruleset Document
   @param pipeline  pipeline name
   @param index     step index
   @param delta     -1 up, +1 down
   @return True if it moved
   """
   lst = steps(doc, pipeline)
   i = _index(lst, index, f"pipeline {pipeline}")
   j = i + delta
   if not 0 <= j < len(lst):
      return False
   lst[i], lst[j] = lst[j], lst[i]
   return True


def set_step(doc: Document, pipeline: str, index: int, key: str, value: Any) -> None:
   """!Changes one key of a step (its kind's keys: let / expr / range, point / on, roll / span); None removes a
   let's range.
   @param doc       ruleset Document
   @param pipeline  pipeline name
   @param index     step index
   @param key       the key
   @param value     text, or [lo, hi] for range
   @return None
   """
   lst = steps(doc, pipeline)
   step = lst[_index(lst, index, f"pipeline {pipeline}")]
   kind = step_kind(step)
   if key not in STEP_KEYS[kind]:
      raise DocumentError(f"a {kind} step has {', '.join(STEP_KEYS[kind])}, not {key!r}")
   if key == "range":
      if value is None:
         step.pop("range", None)
      else:
         step["range"] = _range(value)
      return
   if not isinstance(value, str) or not value.strip():
      raise DocumentError(f"{key}: a non-empty text")
   step[key] = value.strip()


# -- points -----------------------------------------------------------------------------------------------------------

def point_sources() -> list[str]:
   """!Every source a point may list: the battlers' passives, items and statuses and the weather (and the
   holder's passive, item and status).
   @return names, in the engine's order
   """
   return list(_rc().POINT_SOURCES) + list(_rc().HOLDER_SOURCES)


def holders() -> list[str]:
   """!Who a point's value belongs to.
   @return user, target, self
   """
   return list(_rc().HOLDERS)


def _listed_points(doc: Document) -> dict[str, Any]:
   """!The points for reading (nothing created).
   @param doc  ruleset Document
   @return the live dict, or {} when the ruleset has none
   """
   given = doc.data.get(POINTS_KEY)
   return given if isinstance(given, dict) else {}


def point_names(doc: Document) -> list[str]:
   """!The ruleset's points, in id order (the declaration order).
   @param doc  ruleset Document
   @return names
   """
   return list(_listed_points(doc))


def point_entry(doc: Document, name: str) -> JsonDict:
   """!A point by name.
   @param doc   ruleset Document
   @param name  point name
   @return the dict (live)
   @throws DocumentError when there is none
   """
   p = _listed_points(doc).get(name)
   if not isinstance(p, dict):
      raise DocumentError(f"no point {name!r} (points: {', '.join(point_names(doc)) or 'none'})")
   return p


def _sources(value: Any) -> list[str]:
   """!A point's source list, checked against the engine's source names.
   @param value  list of source names
   @return the list
   @throws DocumentError for an unknown or repeated source
   """
   known = point_sources()
   if not isinstance(value, (list, tuple)) or not all(isinstance(s, str) and s in known for s in value):
      raise DocumentError(f"sources are a list of {', '.join(known)}")
   if len(set(value)) != len(value):
      raise DocumentError("a source is listed twice")
   return list(value)


def add_point(doc: Document, name: str, holder: str = DEFAULT_HOLDER, sources: list[str] | None = None,
              rng: list[Any] | None = None) -> None:
   """!Adds a point (its id is the next one).
   @param doc      ruleset Document
   @param name     lower-case identifier
   @param holder   user, target or self
   @param sources  sources in the order they run, or None for none
   @param rng      the clamp of the point's result, or None for [0, 65535] (what handlers see)
   @return None
   """
   rc = _rc()
   if not isinstance(name, str) or not rc.STAT_FORMULA_NAME.fullmatch(name):
      raise DocumentError(f"a point name is a lower-case identifier (got {name!r})")
   if name in _listed_points(doc):
      raise DocumentError(f"there is already a point {name!r}")
   if len(_listed_points(doc)) >= rc.MAX_POINTS:
      raise DocumentError(f"at most {rc.MAX_POINTS} points")
   if holder not in rc.HOLDERS:
      raise DocumentError(f"holder: one of {', '.join(rc.HOLDERS)}")
   points = doc.data.get(POINTS_KEY)
   if not isinstance(points, dict):
      points = doc.data[POINTS_KEY] = {}
   points[name] = {"holder": holder, "sources": _sources(sources or []),
                   "range": _range(rng if rng is not None else list(rc.POINT_VALUE_RANGE))}


def point_users(ruleset: Document, name: str, battle_doc: Document | None = None) -> list[str]:
   """!What uses a point: pipeline steps that run it and (with the battle manifest) the owners with a handler for
   it (handler_owners(): passives, items, statuses, weathers, moves, volatiles, side conditions): a manifest point
   handler, or a `point NAME` member of their effect logic (core.logic.point_users(): the .ceffect sources of the
   project the battle Document belongs to).
   @param ruleset     ruleset Document
   @param name        point name
   @param battle_doc  battle Document, or None for the pipelines only
   @return "where" strings (one per owner, in manifest order)
   """
   found = []
   for pipeline, lst in (ruleset.data.get(PIPELINES_KEY) or {}).items():
      for i, s in enumerate(lst if isinstance(lst, list) else []):
         if isinstance(s, dict) and s.get("point") == name and "on" in s:
            found.append(f"pipeline {pipeline} step {i}")
   if battle_doc is None:
      return found
   uses = logic.point_users(battle_doc)
   # statuses, weathers and the condition records are the structure manifest's
   data = logic.manifest_view(battle_doc)
   kinds = logic.point_owner_lists()
   for key in handler_owners():
      for e in data.get(key, []):
         if isinstance(e, dict) and name in uses.get((key, e.get("name")), []):
            found.append(f"{kinds.get(key, key)} {e.get('name')}")
   return found


def remove_point(doc: Document, name: str, battle_doc: Document | None = None) -> None:
   """!Removes a point nothing uses (the later points' ids move down by one).
   @param doc         ruleset Document
   @param name        point name
   @param battle_doc  battle Document whose handlers are checked too, or None
   @return None
   """
   point_entry(doc, name)
   users = point_users(doc, name, battle_doc)
   if users:
      raise DocumentError(f"point {name!r} is still used by: {', '.join(users[:REFERENCES_SHOWN])}")
   del doc.data[POINTS_KEY][name]



def set_point(doc: Document, name: str, key: str, value: Any) -> None:
   """!Changes a point's holder, sources (the whole list, in order) or range.
   @param doc    ruleset Document
   @param name   point name
   @param key    one of POINT_KEYS
   @param value  holder name, list of sources, or [lo, hi]
   @return None
   """
   p = point_entry(doc, name)
   if key == "holder":
      if value not in holders():
         raise DocumentError(f"holder: one of {', '.join(holders())}")
      p["holder"] = value
   elif key == "sources":
      p["sources"] = _sources(value)
   elif key == "range":
      p["range"] = _range(value)
   else:
      raise DocumentError(f"a point has {', '.join(POINT_KEYS)}, not {key!r}")


def add_source(doc: Document, name: str, source: str, index: int | None = None) -> None:
   """!Adds a source to a point (sources run in list order).
   @param doc     ruleset Document
   @param name    point name
   @param source  one of point_sources()
   @param index   position, or None for the end
   @return None
   """
   p = point_entry(doc, name)
   lst = list(p.get("sources") or [])
   lst.insert(len(lst) if index is None else max(0, min(len(lst), int(index))), source)
   p["sources"] = _sources(lst)


def remove_source(doc: Document, name: str, source: str) -> None:
   """!Removes a source from a point.
   @param doc     ruleset Document
   @param name    point name
   @param source  the source
   @return None
   """
   p = point_entry(doc, name)
   lst = list(p.get("sources") or [])
   if source not in lst:
      raise DocumentError(f"point {name} has no source {source!r}")
   lst.remove(source)
   p["sources"] = lst


def move_source(doc: Document, name: str, source: str, delta: int) -> bool:
   """!Moves a source earlier or later (handlers combine in source order).
   @param doc     ruleset Document
   @param name    point name
   @param source  the source
   @param delta   -1 earlier, +1 later
   @return True if it moved
   """
   p = point_entry(doc, name)
   lst = list(p.get("sources") or [])
   if source not in lst:
      raise DocumentError(f"point {name} has no source {source!r}")
   i = lst.index(source)
   j = i + delta
   if not 0 <= j < len(lst):
      return False
   lst[i], lst[j] = lst[j], lst[i]
   p["sources"] = lst
   return True


# -- analysis ---------------------------------------------------------------------------------------------------------

def bound_ruleset(project: BattleProject) -> tuple[JsonDict | None, bool, str | None]:
   """!The ruleset with its pipelines analysed: against this battle (its stats, moves and tables) when the data
   compiles, else against the ruleset compiler's neutral battle values.
   @param project  BattleProject
   @return (bound ruleset or None, True when analysed against this battle, the battle's or ruleset's error)
   """
   compiled, error = project.compile()
   if compiled is not None:
      return compiled["pipelines"], True, None
   rc = _rc()
   try:
      data = _bc().strip(project.ruleset.data)
      return rc.bind(rc.load(data, project.ruleset.path.name), None, project.ruleset.path.name), False, error
   except rc.RulesetError as e:
      return None, False, str(e)


def pipeline_report(project: BattleProject, name: str) -> tuple[list[StepRow], str | None, bool]:
   """!A pipeline's steps with their analysed ranges (the engine's interval analysis).
   @param project  BattleProject
   @param name     pipeline name
   @return (rows, error or None, True when analysed against this battle): each row has index, kind, var, text,
           bounds (the variable's range after the step), analysed (a let's range before its clamp, else None),
           range (a let's declared clamp, else None) and clamp_active
   """
   _check_pipeline(name)
   bound, own, error = bound_ruleset(project)
   if bound is None:
      return [], error, False
   rows = []
   for i, s in enumerate(bound["pipelines"][name]["steps"]):
      text = s.get("expr", "")
      if s["kind"] == "point":
         text = f"point {s['point']} on {s['var']}"
      elif s["kind"] == "roll":
         text = f"roll {s['var']} in [0, {text})"
      else:
         text = f"let {s['var']} = {text}"
      rows.append({"index": i, "kind": s["kind"], "var": s["var"], "text": text, "bounds": tuple(s["bounds"]),
                   "analysed": tuple(s["analysed"]) if "analysed" in s else None,
                   "range": tuple(s["range"]) if "range" in s else None,
                   "clamp_active": bool(s.get("clamp_active", False))})
   return rows, error, own


# -- running ----------------------------------------------------------------------------------------------------------

class DamageTrace:
   """!One damage calculation, step by step (damage_trace())."""

   def __init__(self, damage: int, decisive: str | None, inputs: dict[str, int], trace: list[TraceStep],
                attacker: JsonDict, defender: JsonDict, hit_type: str | None = None,
                own_type: str | None = None) -> None:
      """!Holds the result.
      @param damage    the damage dealt
      @param decisive  "zero" or "ko" when a decisive type tier decided it (no pipeline ran), else None
      @param inputs    the damage pipeline's inputs
      @param trace     the steps run
      @param attacker  the attacker as point handlers read it (stats, hp, stages, ...)
      @param defender  the defender, likewise
      @param hit_type  the type the hit has (the move_type point's), or None when not known
      @param own_type  the move's own type, or None
      """
      ## The hit's type name (E13b: the move_type point may change the move's own).
      self.hit_type = hit_type
      ## The move's own type name.
      self.own_type = own_type
      ## The damage dealt.
      self.damage = damage
      ## "zero" / "ko" for a decisive type tier, else None.
      self.decisive = decisive
      ## The pipeline's inputs.
      self.inputs = inputs
      ## The steps run: (index, kind, var, value before (point steps), value after, text).
      self.trace = trace
      ## The attacker's battler view.
      self.attacker = attacker
      ## The defender's battler view.
      self.defender = defender

   def lines(self) -> list[str]:
      """!The trace as text (the CLI's `damage --trace`).
      @return lines
      """
      out = ["inputs: " + ", ".join(f"{k} {v}" for k, v in self.inputs.items())]
      if self.hit_type is not None and self.hit_type != self.own_type:
         out.insert(0, f"hit type {self.hit_type} (the move_type point; the move's own: {self.own_type})")
      if self.decisive is not None:
         out.append(f"decisive type tier {self.decisive}: no pipeline runs")
      steps = self.trace   # local name for "in": Doxygen 1.12 misreads "in self.x"
      for index, kind, var, before, value, text in steps:
         change = f"{before} -> {value}" if before is not None else str(value)
         out.append(f"  [{index}] {text}: {var} = {change}")
      out.append(f"damage {self.damage}")
      return out


def _index_of(compiled: JsonDict, kind: str, name: str | None, what: str) -> int | None:
   """!An entry's index in the compiled data.
   @param compiled  BattleProject.compile() result
   @param kind      names list ("moves", "weathers", ...)
   @param name      entry name, or None
   @param what      singular for messages
   @return the index, or None for None
   @throws DocumentError for an unknown name
   """
   if name is None:
      return None
   names = compiled["names"][kind]
   if name not in names:
      raise DocumentError(f"no {what} {name!r}")
   return names.index(name)


def first_slot_passive(compiled: JsonDict, sp: JsonDict) -> int:
   """!The passive a species' first slot gives, as the engine's passive_for() resolves it (C4): the slot's own, or
   for an empty one the first filled rolled slot's (never a slot only given).
   @param compiled  BattleProject.compile() result ("passive_slots", the species' "passives")
   @param sp        compiled species
   @return passive index, or the compiler's NONE8
   """
   none = _bc().NONE8
   own = sp["passives"][0] if sp["passives"] else none
   if own != none:
      return own
   rolled = [k for k, slot in enumerate(compiled.get("passive_slots", [])) if slot["rolled"]]
   return next((sp["passives"][k] for k in rolled if k < len(sp["passives"]) and sp["passives"][k] != none), none)


def battler_view(compiled: JsonDict, species: str, level: int, trait: str | None = None, passive: str | None = None,
                 status: str | None = None, item: str | None = None, genes: int = 0, training: int = 0,
                 hp_pct: int = PERCENT) -> JsonDict:
   """!A creature as the engine's point handlers read it (stats from the ruleset, every stage 0).
   @param compiled  BattleProject.compile() result
   @param species   species name
   @param level     level
   @param trait     trait name, or None (100 % everywhere)
   @param passive   passive name, or None for the species' first slot (first_slot_passive())
   @param status    status name, or None
   @param item      held item name, or None
   @param genes     every stat's gene value
   @param training  every stat's training value
   @param hp_pct    current HP in percent of the maximum
   @return the view (battlec.pipelines.BattlerView): stats, max_hp, hp, level, stages, types, passive, status,
           item (engine indices; status and item 0 = none); E13b: genes (per stat), volatiles and side_conditions
           (bits; none set: with_conditions() sets them), side_active (one battler on its side)
   """
   bc = _bc()
   sp = next((s for s in compiled["species"] if s["name"] == species), None)
   if sp is None:
      raise DocumentError(f"no species {species!r}")
   _index_of(compiled, "traits", trait, "trait")
   count = len(compiled["stats"])
   stats = bc.preview_stats(compiled, species, level, [genes] * count, [training] * count, None, trait)
   pool = next(i for i, st in enumerate(compiled["stats"]) if st["pool"])
   status_index = _index_of(compiled, "statuses", status, "status")
   item_index = _index_of(compiled, "items", item, "item")
   return {"stats": stats, "max_hp": stats[pool], "hp": stats[pool] * hp_pct // PERCENT, "level": level,
           "stages": [0] * len(compiled["stages"]),
           "types": [t for t in sp["types"] if t != bc.NONE8],
           "passive": (first_slot_passive(compiled, sp) if passive is None
                       else _index_of(compiled, "passives", passive, "passive")),
           "status": 0 if status_index is None else status_index + FIRST_LISTED,
           "item": 0 if item_index is None else item_index + FIRST_LISTED,
           "genes": [genes] * count, "volatiles": 0, "side_conditions": 0, "side_active": SIDE_ACTIVE}


def with_conditions(compiled: JsonDict, view: JsonDict, volatiles: Sequence[str] = (),
                    side_conditions: Sequence[str] = (), side_active: int | None = None) -> JsonDict:
   """!A battler view with volatiles on it and side conditions on its side (the point handlers of those run too,
   E13b: battlec.pipelines point_runner() reads the bits in data order).
   @param compiled         BattleProject.compile() result
   @param view             battler_view() result (changed and returned)
   @param volatiles        volatile names on the battler
   @param side_conditions  side condition names on its side
   @param side_active      battlers active on its side (side(X).active_count), or None to keep it
   @return the view
   @throws DocumentError for an unknown name or a count outside 1..MAX_POSITIONS
   """
   for key, names, what in (("volatiles", volatiles, "volatile"), ("side_conditions", side_conditions,
                                                                     "side condition")):
      for name in names:
         view[key] |= 1 << _index_of(compiled, key, name, what)
   if side_active is not None:
      most = int(_bc().MAX_POSITIONS)
      if not 1 <= side_active <= most:
         raise DocumentError(f"battlers on a side: 1 to {most}, got {side_active}")
      view["side_active"] = side_active
   return view


def type_effect(compiled: JsonDict, move_type: int, target: JsonDict) -> JsonDict:
   """!A move type's chart result against a battler, as the engine computes it (the battle compiler's
   type_effect(): damage.cpp type_effect()).
   @param compiled   BattleProject.compile() result
   @param move_type  type index
   @param target     battler view
   @return {"decisive": None | "zero" | "ko", "tier", "exp" (exponent sum), "q8" (combined factor), "factors"
           (the scaling tiers' factors in type order: run_pipeline types=)}
   """
   return _bc().type_effect(compiled["chart"], len(compiled["types"]), move_type, target["types"])


def stage_range(compiled: JsonDict, stat: int) -> tuple[int, int]:
   """!The values a stat's stage takes (its range; (0, 0) for a stat without a stage).
   @param compiled  BattleProject.compile() result
   @param stat      stat index
   @return (lo, hi)
   """
   index = compiled["stats"][stat]["stage"]
   return tuple(compiled["stages"][index]["range"]) if index != _bc().NONE8 else (0, 0)


def move_stage_ranges(project: BattleProject, move: str) -> tuple[tuple[int, int], tuple[int, int]] | None:
   """!The stage ranges of a damaging move's offense and defense stats (the calculator's stage inputs).
   @param project  BattleProject
   @param move     move name
   @return (offense (lo, hi), defense (lo, hi)), or None when the data does not compile or the move is not a
           damaging move
   """
   compiled, _error = project.compile()
   if compiled is None or move not in compiled["names"]["moves"]:
      return None
   m = compiled["moves"][compiled["names"]["moves"].index(move)]
   cat = compiled["categories"][m["category"]]
   if cat["offense"] == _bc().NONE8:
      return None
   return stage_range(compiled, cat["offense"]), stage_range(compiled, cat["defense"])


def damage_trace(project: BattleProject, attacker: str, defender: str, move: str, level: int = DEFAULT_LEVEL,
                 roll: int = 0, crit: bool = False, weather: str | None = None, status: str | None = None,
                 spread: bool = False, *, attacker_trait: str | None = None, defender_trait: str | None = None,
                 passive: str | None = None, item: str | None = None, genes: int = 0, training: int = 0,
                 hp_pct: int = PERCENT, offense_stage: int = 0, defense_stage: int = 0,
                 defender_level: int | None = None, attacker_volatiles: Sequence[str] = (),
                 defender_volatiles: Sequence[str] = (), attacker_side: Sequence[str] = (),
                 defender_side: Sequence[str] = (), attacker_active: int | None = None,
                 defender_active: int | None = None) -> DamageTrace:
   """!One hit's damage as the engine's battle::damage_preview() computes it: the decisive type tiers, then the
   damage pipeline (ruleset_compiler.run_pipeline) with the point handlers run by the battle compiler's
   point_runner(). Unsaved edits are included.
   @param project         BattleProject (its data must compile)
   @param attacker        attacking species
   @param defender        defending species
   @param move            move name (its category must be damaging)
   @param level           attacker level (and the defender's unless defender_level is given)
   @param roll            the damage roll: the index of the draw (clamped below each roll's span; 0 = lowest)
   @param crit            a critical hit
   @param weather         weather name, or None
   @param status          the attacker's status, or None
   @param spread          a spread hit (several targets)
   @param attacker_trait  attacker's trait, or None
   @param defender_trait  defender's trait, or None
   @param passive         attacker's passive, or None for its species' first
   @param item            attacker's held item, or None
   @param genes           every stat's gene value of both creatures
   @param training        every stat's training value of both creatures
   @param hp_pct          attacker's HP in percent of its maximum
   @param offense_stage   stage of the attacker's offense stat (the move's category's)
   @param defense_stage   stage of the defender's defense stat
   @param defender_level  defender level, or None for the attacker's
   @param attacker_volatiles  volatiles on the attacker (their point handlers run; E13b)
   @param defender_volatiles  volatiles on the defender
   @param attacker_side       side conditions on the attacker's side
   @param defender_side       side conditions on the defender's side (e.g. a screen)
   @param attacker_active     battlers active on the attacker's side, or None for one
   @param defender_active     battlers active on the defender's side, or None for one
   @return DamageTrace (E13b: the move's type is the move_type point's, the engine's move_type_of(): the chart,
           same_type and the handlers' move.type read it)
   @throws DocumentError when the data does not compile or a name is unknown
   """
   compiled, error = project.compile()
   if compiled is None:
      raise DocumentError(error)
   # the values the data gives a creature (S11): levels to rules.level_max, genes / training to the layout's widths
   battle.check_level(project.structure, level)
   if defender_level is not None:
      battle.check_level(project.structure, defender_level, "defender level")
   record.check_stat_inputs(project.battle, {"gene": [genes], "training": [training]})
   bc, rc = _bc(), _rc()
   m_index = _index_of(compiled, "moves", move, "move")
   w_index = _index_of(compiled, "weathers", weather, "weather")
   user = battler_view(compiled, attacker, level, attacker_trait, passive, status, item, genes, training, hp_pct)
   target = battler_view(compiled, defender, level if defender_level is None else defender_level, defender_trait,
                         None, None, None, genes, training)
   with_conditions(compiled, user, attacker_volatiles, attacker_side, attacker_active)
   with_conditions(compiled, target, defender_volatiles, defender_side, defender_active)
   m = compiled["moves"][m_index]
   cat = compiled["categories"][m["category"]]
   if cat["offense"] == bc.NONE8:
      raise DocumentError(f"{move}'s category {compiled['names']['categories'][m['category']]} is not damaging")
   weather_index = bc.NONE8 if w_index is None else w_index
   off, dfn = compiled["stats"][cat["offense"]], compiled["stats"][cat["defense"]]
   # A stage value is clamped to its stage's range, as the engine does.
   if off["stage"] != bc.NONE8:
      lo, hi = compiled["stages"][off["stage"]]["range"]
      user["stages"][off["stage"]] = max(lo, min(hi, offense_stage))
   if dfn["stage"] != bc.NONE8:
      lo, hi = compiled["stages"][dfn["stage"]]["range"]
      target["stages"][dfn["stage"]] = max(lo, min(hi, defense_stage))
   # The hit's type first (no crit yet, as the engine's move_type_of()); the rest of the hit reads it, the
   # handlers' move.type too (point_runner(move_type=): the engine's PipelineCtx.move_type).
   data_type = m["type"]
   typed = bc.move_type_of(compiled, bc.point_runner(compiled, user, target, move=m_index, weather=weather_index),
                           m_index)
   fx = type_effect(compiled, typed, target)
   decisive = fx["decisive"]
   type_names = compiled["names"]["types"]
   types = (type_names[typed], type_names[data_type])   # (the hit's, the move's own)
   inputs = {"level": user["level"], "move_power": m["power"], "offense_raw": user["stats"][cat["offense"]],
             "offense_stage": user["stages"][off["stage"]] if off["stage"] != bc.NONE8 else 0,
             "defense_raw": target["stats"][cat["defense"]],
             "defense_stage": target["stages"][dfn["stage"]] if dfn["stage"] != bc.NONE8 else 0,
             "crit": int(crit), "spread": int(spread), "same_type": int(typed in user["types"]),
             "type_exp": fx["exp"], "offense_stage_id": off["stage"], "defense_stage_id": dfn["stage"]}
   if decisive is not None:
      zero = bc.DECISIVE[ZERO_DECISIVE]   # no damage; the other decisive kind takes the target's whole HP
      return DamageTrace(0 if decisive == zero else target["hp"], decisive, inputs, [], user, target, *types)
   run_point = bc.point_runner(compiled, user, target, move=m_index, weather=weather_index, crit=int(crit),
                               move_type=typed)
   seen: list[int] = []

   def point(name: str, v: int) -> int | None:
      """!Runs a point's handlers, noting the value it was given."""
      seen.append(v)
      return run_point(name, v)

   bound = compiled["pipelines"]
   out = rc.run_pipeline(bound, DAMAGE, inputs, point, roll, types=fx["factors"])
   pipeline_steps = bound["pipelines"][DAMAGE]["steps"]
   before = iter(seen)
   trace = []
   for index, kind, var, value in out["trace"]:
      s = pipeline_steps[index]
      if kind == "point":
         text = f"point {s['point']} on {var}"
      elif kind == "roll":
         text = f"roll {var} in [0, {s['expr']})"
      else:
         text = f"let {var} = {s['expr']}"
      trace.append((index, kind, var, next(before) if kind == "point" else None, value, text))
   return DamageTrace(out["outputs"][DAMAGE], None, inputs, trace, user, target, *types)


def pipeline_trace(project: BattleProject, name: str, inputs: dict[str, int],
                   roll: int = 0) -> tuple[dict[str, int], list[TraceStep]]:
   """!Runs any pipeline on given inputs, without point handlers (each point leaves its value).
   @param project  BattleProject
   @param name     pipeline name
   @param inputs   every input of the pipeline (pipeline_inputs()); the stage ids may be left out: speed_stage_id
                   then names the order stat's own stage (the stat the engine orders turns by, E7: sample rulesets
                   scale it with stage_scale(speed_stage_id, ...)), offense_stage_id / defense_stage_id no stage
                   (x1; damage_trace() passes the move's category's)
   @param roll     the index of each draw (clamped below its span)
   @return (outputs, steps run)
   @throws DocumentError when the ruleset does not bind, an input is missing, or a step needs what the inputs
           cannot give (type_scale() in the multiply / sequential modes needs the target's tiers: damage_trace())
   """
   _check_pipeline(name)
   rc = _rc()
   missing = [n for n in pipeline_inputs(name) if n not in inputs and n not in rc.INPUT_DEFAULTS]
   if missing:
      raise DocumentError(f"{name} needs {', '.join(missing)}")
   bound, _own, error = bound_ruleset(project)
   if bound is None:
      raise DocumentError(error)
   inputs = dict(inputs)
   if SPEED_STAGE_ID in pipeline_inputs(name) and SPEED_STAGE_ID not in inputs:
      compiled, _error = project.compile()
      order = [st for st in (compiled or {}).get("stats", []) if st.get("order")]
      if order and order[0]["stage"] != _bc().NONE8:
         inputs[SPEED_STAGE_ID] = order[0]["stage"]
   try:
      out = rc.run_pipeline(bound, name, inputs, None, roll)
   except rc.RulesetError as e:
      raise DocumentError(str(e)) from None
   rows = {r["index"]: r["text"] for r in pipeline_report(project, name)[0]}
   trace = [(i, kind, var, None, value, rows.get(i, var)) for i, kind, var, value in out["trace"]]
   return out["outputs"], trace
