"""!Battle data being edited: a capsule.battle/1 manifest, its ruleset, and
the structure and effect sources it names.

A BattleProject holds one Document per file, each with its own undo history
(D-23 §3.1): the battle manifest (content: types, moves, species, parties,
...), its ruleset (formulas), the structure manifest the battle names under
"structure" (capsule.structure/1, structure.json: the record, stats, stages,
rules, chart, categories, condition records, formats, terms, ...; the
engine's battlec manifest.STRUCTURE_KEYS decide which key is where, E5s) and
the effect sources it lists under "effects" (.ceffect text files, as
SourceDocuments). It compiles them with the engine's battle compiler (unsaved
edits included), previews stats and formulas with the engine's own
evaluator, and saves them together. A file the manifest names but that does
not exist yet starts empty and is written by the next save. A single-file
battle.json (structure keys inline, the form before E5s) does not open: open()
raises NeedsSplit and split() migrates it with the engine's battle_split tool.
Nothing here depends on a user interface.

The battle and structure Documents are partners (core.document): an edit()
of either one may change both, as one undo step. Helpers take either
Document of a project and find the key they read where it lives (part_of());
a Document opened on its own holds every key itself (a merged view, e.g.
the engine's view_of()).

Editing helpers change the manifests' lists by kind ("types",
"categories", "moves", "species", "parties", "presenters", "passives",
"items", "statuses", "weathers", "traits", "formats"; categories, statuses,
weathers and formats are structure); renames follow every reference in both
manifests, the effect logic's included (core.logic: the project's .ceffect
sources and the manifests' point handler code, through the AST) and the
game's saved bench scenarios (core.bench.follow_rename(), as the project's
scenario Documents: BattleProject.scenarios, saved and counted unsaved with
the rest), removals are refused while something still refers to the entry
(its own logic included) or the ruleset no longer binds without it
(check_ruleset_kept()). Adding an entry under a taken name is refused. Call
them inside doc.edit(): the source and scenario edits a rename makes join
that undo step.

The game's words for its concepts (party, trait, passive, ...) are the
manifest's "terms" section over the engine's neutral defaults: terms() and
kind_label() give them to editors.
"""
from __future__ import annotations

import copy
import inspect
import re
from pathlib import Path
from typing import Any

from . import document, engine, expressions, logic, manifest_io, templates
from .document import Document, DocumentError

## A parsed JSON object (a manifest, an entry of one of its lists, a compiled result).
JsonDict = dict[str, Any]
## One row of BattleProject.ruleset_report(): (slot, analysed bounds, declared range, clamp can engage, expression).
FormulaRow = tuple[str, tuple[int, int], tuple[int, int], bool, str]
## How reports and panels name what the ruleset leaves to the engine (an optional pipeline, core.pipelines).
ENGINE_DEFAULT = "engine default"
## A term's two forms: {"one": word, "many": words}.
Term = dict[str, str]

## Battle manifest schema (the content manifest, battlec manifest.BATTLE_SCHEMA).
BATTLE_SCHEMA = "capsule.battle/1"
## Ruleset manifest schema (the engine's ruleset_compiler.SCHEMA).
RULESET_SCHEMA = "capsule.ruleset/2"
## Structure manifest schema (D-23 §2, E5s: structure.json; battlec manifest.STRUCTURE_SCHEMA).
STRUCTURE_SCHEMA = "capsule.structure/1"
## File name of a new battle's structure manifest, next to its battle.json (battlec manifest.DEFAULT_STRUCTURE_FILE).
STRUCTURE_FILE = "structure.json"
## File name of a new battle's ruleset, next to its battle.json.
RULESET_FILE = "ruleset.json"
## Schema of a SourceDocument's data: the studio's wrapper of an effect source's text (the file is plain text).
EFFECT_SOURCE_SCHEMA = "capsule.effect-source/1"
## Species key: the moves `teach` may give it (engine C6).
TEACHABLE_KEY = "teachable"
## B1: a species' combine moves (the moves a combination's move source combine_moves gives).
COMBINE_MOVES_KEY = "combine_moves"
## The project manifest's key of the game's scripts manifest (core.project.GAME_FILES).
SCRIPTS_FILE_KEY = "scripts"
## Battle manifest key naming the structure manifest (a path relative to the battle manifest).
STRUCTURE_KEY = "structure"
## Structure key of the category-by-type rule (E11; core.structure.categories edits it).
BY_TYPE_KEY = "category_by_type"


def type_tables() -> list[str]:
   """!The structure keys of the tables that name every type with a category: category_by_type, and the hit types'
   categories (engine C5 HIT_CATEGORY_KEY, when this engine has it); a type or category rename follows them.
   @return keys
   """
   hit = getattr(engine.tool("battle_compiler"), "HIT_CATEGORY_KEY", None)
   return [BY_TYPE_KEY] + ([hit] if isinstance(hit, str) else [])
## Battle manifest key listing the effect sources (paths relative to the battle manifest).
EFFECTS_KEY = "effects"
## File name ending of an effect source.
EFFECT_SUFFIX = ".ceffect"

## Editable lists of the battle data, in the order editors show them (categories, statuses, weathers and formats
## are in the structure manifest: part_of()).
KINDS = ["types", "categories", "moves", "species", "parties", "presenters", "passives", "items", "statuses",
         "weathers", "traits", "formats"]
## Singular names for messages.
SINGULAR = {"types": "type", "categories": "category", "moves": "move", "species": "species", "parties": "party",
            "presenters": "presenter", "passives": "passive", "items": "item", "statuses": "status",
            "weathers": "weather", "traits": "trait", "formats": "format"}
## The terms concept naming each kind (the game's word for it, see terms()).
KIND_CONCEPTS = {"types": "type", "categories": "category", "moves": "move", "species": "species",
                 "parties": "party", "presenters": "presenter", "passives": "passive", "items": "item",
                 "statuses": "status", "weathers": "weather", "traits": "trait", "formats": "format"}

## The range a new stat, accuracy or evasion stage starts with: an editor default, no engine value (S17 audit: the
## ruleset compiler's own DEFAULT_STAGE_RANGE spans the whole STAGE_LIMIT, a long table to fill; core.structure.
## stages.default_range() clamps this to the limit, and the game widens a stage's range when it wants more).
NEUTRAL_STAGE_RANGE = [-6, 6]
## The range a new crit stage starts with: an editor default likewise (the compiler's DEFAULT_CRIT_RANGE spans 0 to
## STAGE_LIMIT).
NEUTRAL_CRIT_RANGE = [0, 4]
## The built-in template new battle data starts from (core.templates: capsule_studio/templates/blank): neutral,
## minimal data that compiles (the hit points only, no PP or other move pool, no condition records, no logic).
BLANK_TEMPLATE = "blank"
## Files of the Blank template, by the manifest they start.
BLANK_FILES = {BATTLE_SCHEMA: "battle.json", STRUCTURE_SCHEMA: STRUCTURE_FILE, RULESET_SCHEMA: RULESET_FILE}


def blank_template() -> templates.Template:
   """!The built-in Blank template (BattleProject.create() and `battle FILE new` start from it).
   @return Template
   """
   return templates.load(templates.BUILTIN_FOLDER / BLANK_TEMPLATE / templates.TEMPLATE_FILE, templates.BUILTIN)


def _blank(schema: str) -> JsonDict:
   """!One manifest of the Blank template, with editor.template recorded as applying it records it (the template's
   own notes left out).
   @param schema  BATTLE_SCHEMA, STRUCTURE_SCHEMA or RULESET_SCHEMA
   @return a fresh dict
   """
   t = blank_template()
   data = manifest_io.load(t.folder / BLANK_FILES[schema])
   data[templates.EDITOR_KEY] = {templates.TEMPLATE_KEY: {"id": t.id, "version": t.version}}
   return data


def new_battle() -> JsonDict:
   """!A new battle manifest (the content): the Blank template's battle.json; new_structure() is the structure
   manifest it names.
   @return a fresh dict
   """
   return _blank(BATTLE_SCHEMA)


def new_structure() -> JsonDict:
   """!A new structure manifest: the Blank template's structure.json (the record in the object form; the turn and
   the generation list left to the engine's defaults).
   @return a fresh dict
   """
   return _blank(STRUCTURE_SCHEMA)


def new_ruleset() -> JsonDict:
   """!A new ruleset: the Blank template's ruleset.json (neutral integer formulas and pipelines that only do what
   the data says).
   @return a fresh dict
   """
   return _blank(RULESET_SCHEMA)


## Messages of a new battle manifest (the Blank template's): neutral English, game words through `{@concept}` terms.
DEFAULT_MESSAGES = dict(new_battle()["messages"])
## A new battle manifest (the Blank template's battle.json; read-only: new_battle() gives a copy to change).
NEW_BATTLE = new_battle()
## A new structure manifest (the Blank template's structure.json; read-only: new_structure() gives a copy).
NEW_STRUCTURE = new_structure()


def structure_keys() -> tuple[str, ...]:
   """!The keys of the structure manifest (the engine's battlec manifest.STRUCTURE_KEYS, re-exported by
   battle_compiler); every other key is the battle manifest's.
   @return key names
   """
   return tuple(engine.tool("battle_compiler").STRUCTURE_KEYS)


def _pair(doc: Document) -> tuple[Document, Document] | None:
   """!The battle and structure manifests a Document is one of: its partner (BattleProject links them), or for
   the ruleset its project's.
   @param doc  a manifest Document
   @return (battle Document, structure Document), or None for a Document on its own
   """
   wanted = {BATTLE_SCHEMA: STRUCTURE_SCHEMA, STRUCTURE_SCHEMA: BATTLE_SCHEMA}.get(doc.schema)
   partner = next((d for d in doc.partners if d.schema == wanted), None) if wanted is not None else None
   if partner is not None:
      return (doc, partner) if doc.schema == BATTLE_SCHEMA else (partner, doc)
   project = logic.project_of(doc)
   return (project.battle, project.structure) if project is not None else None


def part_of(doc: Document, key: str) -> Document:
   """!The Document holding a manifest key: the structure manifest for a structure key (structure_keys()), the
   battle manifest otherwise, of the battle data @p doc is one of (_pair()).
   @param doc  any manifest Document of a BattleProject, or a Document on its own (it holds every key: returned)
   @param key  a top-level manifest key ("stats", "moves", ...)
   @return Document
   """
   pair = _pair(doc)
   if pair is None:
      return doc
   return pair[1] if key in structure_keys() else pair[0]


def data_of(doc: Document, key: str) -> JsonDict:
   """!The manifest data holding a key (part_of()'s Document's data; live: change it only inside an edit()).
   @param doc  any manifest Document of a BattleProject (or one on its own)
   @param key  a top-level manifest key
   @return the manifest dict
   """
   return part_of(doc, key).data


def structure_doc(doc: Document) -> Document:
   """!The structure manifest of the battle data a Document is one of.
   @param doc  any manifest Document of a BattleProject (or one on its own: returned)
   @return Document
   """
   pair = _pair(doc)
   return pair[1] if pair is not None else doc


def merged(doc: Document) -> JsonDict:
   """!Both manifests' keys in one dict (the structure's schema left out), for code that reads the battle data as
   one or changes values inside its sections: the sections are the Documents' own (live) objects, so a change
   inside one changes its manifest. Assigning a top-level key of the dict changes neither manifest: use
   data_of() for that.
   @param doc  any manifest Document of a BattleProject (or one on its own: a copy of its keys)
   @return dict
   """
   pair = _pair(doc)
   if pair is None:
      return dict(doc.data)
   return {**pair[0].data, **{k: v for k, v in pair[1].data.items() if k != "schema"}}


def content_doc(doc: Document) -> Document:
   """!The battle manifest (the content) of the battle data a Document is one of.
   @param doc  any manifest Document of a BattleProject (or one on its own: returned)
   @return Document
   """
   pair = _pair(doc)
   return pair[0] if pair is not None else doc


def binding_content(content: JsonDict, structure: JsonDict, plain: bool) -> JsonDict:
   """!A content manifest holding only what binding the ruleset to the structure reads (ruleset_binding_problem()):
   its ruleset and structure, its types by name, its moves (the structure's fallback move and the moves' ranges
   the pipelines take) and its messages; no species, parties, logic or other content, whose errors are not the
   ruleset's.
   @param content    the battle manifest's data
   @param structure  the structure manifest's data (the move resources' base fields)
   @param plain      True: every move with binding_move_plain()'s values and NEW_RESOURCE_BASE bases and the messages a
                     placeholder each (no value of the content can be in error); False: the moves' own values
   @return the manifest (a new dict)
   """
   out: JsonDict = {k: content[k] for k in (*BINDING_KEYS, STRUCTURE_KEY) if k in content}
   types = [t["name"] for t in content.get("types", []) if isinstance(t, dict) and isinstance(t.get("name"), str)]
   out["types"] = [{"name": name, "color": 0} for name in types]
   resources = structure.get("resources")
   bases = [r["base"] for r in resources if isinstance(r, dict) and r.get("scope") == "move"
            and isinstance(r.get("base"), str)] if isinstance(resources, list) else []
   plain_values = binding_move_plain()
   moves = []
   for m in content.get("moves", []):
      if not isinstance(m, dict) or not isinstance(m.get("name"), str):
         continue
      move: JsonDict = {"name": m["name"]}   # the engine's default target
      if m.get("type") in types:
         move["type"] = m["type"]
      elif types:
         move["type"] = types[0]
      if isinstance(m.get("category"), str):
         move["category"] = m["category"]
      for key in BINDING_MOVE_FIELDS:   # a field the move leaves out stays out (a support move has no power)
         if key in m:
            move[key] = plain_values[key] if plain else m[key]
      for base in bases:
         move[base] = NEW_RESOURCE_BASE if plain or base not in m else m[base]
      moves.append(move)
   out["moves"] = moves
   messages = content.get("messages")
   given = messages if isinstance(messages, dict) else {}
   if plain or not isinstance(messages, dict):
      # the required messages and the optional ones the content gives (the structure may name them), each its key
      keys = [*engine.tool("battle_compiler").REQUIRED_MESSAGES, *(k for k in given if isinstance(k, str))]
      messages = {key: key for key in keys}
   out["messages"] = messages
   return out


def binding_structure(structure: JsonDict) -> JsonDict:
   """!A structure manifest without the sections whose own errors are not the ruleset's (S11: an unrelated error
   inside structure.json must not hide the ruleset's): the condition records keep their names (the ruleset's
   point handlers may name them) as new records of their kind (NEW_ENTRY), the terms and passive slots are the
   engine's defaults, the formats, learn and exp_policy the Blank template's. What the ruleset binds to (the record
   layout, stats, stages, categories, rules, resources and the turn their regen needs, chart, growth, generation,
   move flags and tags) is kept as it is: an error there may still come first (ruleset_binding_problem()).
   @param structure  the structure manifest's data
   @return the manifest (a new dict)
   """
   out = copy.deepcopy(structure)
   for key in BINDING_RECORD_LISTS:
      if isinstance(out.get(key), list):
         out[key] = [{**copy.deepcopy(NEW_ENTRY.get(key, {})), "name": e["name"]} for e in out[key]
                     if isinstance(e, dict) and isinstance(e.get("name"), str)]
   for key in BINDING_DROPPED:
      out.pop(key, None)
   for key in BINDING_BLANK:
      if key in NEW_STRUCTURE:
         out[key] = copy.deepcopy(NEW_STRUCTURE[key])
   return out


def ruleset_binding_problem(project: Any) -> str | None:
   """!The ruleset's own error against the structure as the Documents hold it now, apart from the other files'
   errors (C4, S11): compiles the structure with binding_content() (first the moves' own values, then plain ones
   when the content's values are in error themselves), and then the structure's binding_structure() (an error of a
   condition record, the terms, passive slots, formats, learn or exp_policy does not hide the ruleset's).
   @param project  the BattleProject
   @return the ruleset's message, or None (it binds, or an error of a section the ruleset binds to comes first:
           the layout, stats, stages, categories, rules, resources, turn, chart, growth, generation, move
           flags, tags)
   """
   bc = engine.tool("battle_compiler")
   prefix = project.ruleset.path.name + ":"
   attempts = ((False, project.structure.data), (True, project.structure.data),
               (True, binding_structure(project.structure.data)))
   for plain, structure in attempts:
      sources = project.sources()
      if structure is not project.structure.data:
         sources[project.structure.path] = structure
      sources[project.battle.path] = binding_content(project.battle.data, structure, plain)
      try:
         bc.compile_battle(project.battle.path, None, sources, **project.scripts_option(bc))
      except Exception as e:   # as error_now()
         if str(e).startswith(prefix):
            return str(e)
         continue
      return None
   return None


def ruleset_problem(doc: Document) -> str | None:
   """!The error the ruleset gives against the battle data as the Documents hold it now (its pipelines and points
   bind to the data's stats, stages, ...): the compile error when it is the ruleset's; when another file's error
   comes first, the ruleset's binding on its own (ruleset_binding_problem(), C4: an unrelated error must not hide
   it).
   @param doc  any manifest Document of a BattleProject (or one on its own: None)
   @return the message, or None (the ruleset binds, or no project)
   """
   project = logic.project_of(doc)
   if project is None:
      return None
   error = project.error_now()
   prefix = project.ruleset.path.name + ":"
   if error is None or error.startswith(prefix):
      return error
   return ruleset_binding_problem(project)


def check_ruleset_kept(doc: Document, what: str, before: str | None) -> None:
   """!Refuses a removal the ruleset still needs (call it inside the edit, after the removal: raising puts the data
   back), like the removals effect logic refuses: the ruleset's pipelines or points name what went (F9 [S14]).
   @param doc     any manifest Document of a BattleProject
   @param what    what was removed ("stage 'critical'")
   @param before  ruleset_problem() before the removal (an error the ruleset had already is not this removal's)
   @return None
   @throws DocumentError when the ruleset no longer binds
   """
   after = ruleset_problem(doc)
   if after is not None and after != before:
      raise DocumentError(f"{what} is still needed by the ruleset: {after}")


## A new ruleset (the Blank template's ruleset.json; read-only: new_ruleset() gives a copy).
NEW_RULESET = new_ruleset()

## Fields of a new entry per kind (name added by add_entry; a move's type and category, its base of each move
## resource (NEW_RESOURCE_BASE), a species' type, growth and base stats and a party's AI flags are filled in from
## the data). A new move states no accuracy, target or flags: the engine's defaults (S11: no closed flag list).
NEW_ENTRY = {
   "types": {"color": 0},
   "categories": {},
   "moves": {"type": None, "category": None, "power": 50},
   "species": {"types": [None], "base": None, "passives": [], "growth": None, "exp_yield": 50, "learnset": []},
   "parties": {"presenters": [], "reward": 0, "members": []},
   "presenters": {"intro": "{party} challenges you!"},
   "passives": {},
   "items": {},
   "statuses": {"texts": {"inflicted": "{user} was afflicted!", "cured": "{user} recovered.",
                          "already": "{user} is already afflicted!"}},
   "weathers": {"turns": 5, "texts": {"started": "The weather changed!", "continues": "The weather continues.",
                                      "ended": "The weather cleared."}},
   "traits": {},
   "formats": {"sides": [[0], [1]], "range": "all", "layout": [[64, 92], [176, 52]]},
}

## Base a new move states for each move resource (the field the resource's "base" names; the engine has no default).
NEW_RESOURCE_BASE = 10
## Content keys binding_content() keeps as they are (besides the structure's): the schema, id and ruleset.
BINDING_KEYS = ("schema", "id", "ruleset")
## Structure lists binding_structure() keeps by name only (each a new record of its kind: NEW_ENTRY).
BINDING_RECORD_LISTS = ("statuses", "weathers", "volatiles", "side_conditions", "field_conditions")
## Structure sections binding_structure() leaves out (the engine's defaults).
BINDING_DROPPED = ("terms", "passive_slots")
## Structure sections binding_structure() takes from the Blank template (NEW_STRUCTURE).
BINDING_BLANK = ("formats", "learn", "exp_policy")
## Move fields the ruleset's pipelines take ranges of (binding_content(): the move's own, or binding_move_plain()'s).
BINDING_MOVE_FIELDS = ("power", "accuracy", "crit_stage")


def binding_move_plain() -> JsonDict:
   """!The plain value of each BINDING_MOVE_FIELDS field: a new move's power, the engine's default accuracy (the
   compiler's PERCENT: never in error) and no added crit stage.
   @return {field: value}
   """
   return {"power": NEW_ENTRY["moves"]["power"], "accuracy": engine.tool("battle_compiler").PERCENT,
           "crit_stage": 0}


## Base stat a new species starts with, for every stat.
NEW_BASE_STAT = 50
## Most references a refused removal lists in its message.
REFERENCES_SHOWN = 6
## Length of a learnset entry: [level, move].
LEARNSET_ENTRY_LENGTH = 2
## Number unique_name() appends first ("base 2"; the unnumbered name counts as the first).
FIRST_COPY_NUMBER = 2
## The side whose presenters intro() shows by default (the player's foes: side 0 is the player's).
FOE_SIDE = 1
## Value of "terms CONCEPT -" that puts a concept back to the engine's default word.
TERM_RESET = "-"


class SourceDocument(Document):
   """!A text source file (an effect source, .ceffect) as a Document: its text
   is data["text"], edited inside edit() like any manifest, so it has its own
   undo history. open() and save() read and write the plain text (UTF-8)."""

   def __init__(self, text: str = "", path: str | Path | None = None) -> None:
      """!Wraps a source's text.
      @param text  the file's text
      @param path  its file, or None
      """
      super().__init__({"schema": EFFECT_SOURCE_SCHEMA, "text": text}, path, EFFECT_SOURCE_SCHEMA)

   @classmethod
   def open(cls, path: str | Path, schema: str = EFFECT_SOURCE_SCHEMA) -> SourceDocument:
      """!Reads a source file.
      @param path    the file
      @param schema  EFFECT_SOURCE_SCHEMA (the only one a source has)
      @return SourceDocument
      @throws DocumentError when it is not UTF-8 text
      """
      try:
         text = Path(path).read_text(encoding="utf-8")
      except UnicodeDecodeError as e:
         raise DocumentError(f"{path}: not UTF-8 text ({e.reason})") from None
      return cls(text, path)

   @property
   def text(self) -> str:
      """!The source text.
      @return str
      """
      return self.data.get("text", "")

   def save(self, path: str | Path | None = None) -> None:
      """!Writes the text.
      @param path  new file path, or None for the current one
      @return None
      """
      # Through another name: Doxygen 1.12 takes members assigned here for undocumented ones of this class.
      doc = self
      if path is not None:
         doc.path = Path(path).resolve()
      target = doc.path
      if target is None:
         raise DocumentError("no file name; pass a path")
      target.parent.mkdir(parents=True, exist_ok=True)
      target.write_text(doc.data.get("text", ""), encoding="utf-8")
      doc.dirty = False
      doc._notify()


def _named_file(battle: Document, rel: object, what: str) -> Path:
   """!A file the battle manifest names, relative to it.
   @param battle  battle Document (with a path)
   @param rel     the manifest's value
   @param what    what it names (messages)
   @return absolute Path
   @throws DocumentError when the value is not a relative path
   """
   if not isinstance(rel, str) or not rel.strip() or Path(rel).is_absolute():
      raise DocumentError(f"{battle.path.name}: {what} must be a path relative to it, got {rel!r}")
   return (battle.path.parent / rel).resolve()


def _open_or_start(path: Path, schema: str) -> Document:
   """!Opens a manifest the battle names, or starts an empty one written by the next save.
   @param path    its file
   @param schema  its schema
   @return Document (dirty when the file did not exist)
   """
   if path.exists():
      return Document.open(path, schema)
   doc = Document(copy.deepcopy(document.EMPTY[schema]), path, schema)
   doc.dirty = True
   return doc


class NeedsSplit(DocumentError):
   """!A single-file battle manifest (the form before E5s: the structure keys inline, no "structure"): split() it
   into battle.json + structure.json to open it."""

   def __init__(self, path: Path, keys: list[str]) -> None:
      """!Describes the refusal.
      @param path  the battle manifest
      @param keys  the structure keys it holds
      """
      super().__init__(f"{path.name}: single-file battle data (the structure keys {', '.join(keys)} are inline); "
                       f"split it into {path.name} + {split_target(path).name} (capsule-studio battle {path} split) "
                       "to open it")
      ## The battle manifest.
      self.path = path
      ## The structure keys it holds.
      self.keys = keys


def split_target(path: str | Path) -> Path:
   """!The structure manifest split() writes for a single-file battle manifest (battlec structure_file_for():
   structure.json next to a battle.json, STEM.structure.json next to any other name).
   @param path  the battle manifest
   @return the file
   """
   path = Path(path).resolve()
   return path.parent / engine.tool("battle_compiler").structure_file_for(path.name)


def split(path: str | Path, check: bool = False) -> tuple[Path, list[str]]:
   """!Migrates a single-file battle manifest with the engine's battle_split tool (split_file()): the structure
   keys move, unchanged and in order, to a structure manifest next to it (split_target()), which the rewritten
   battle manifest names under "structure".
   @param path   the battle manifest
   @param check  only report what would move (nothing written)
   @return (the structure manifest, the keys moved)
   @throws DocumentError when the engine refuses it (not capsule.battle/1, already split, the target exists)
   """
   tool = engine.tool("battle_split")
   try:
      _battle, structure, st_path = tool.split_file(Path(path), None, write=not check)
   except engine.tool("battle_compiler").ManifestError as e:
      raise DocumentError(str(e)) from None
   return Path(st_path).resolve(), [k for k in structure if k in structure_keys()]


class BattleProject:
   """!A battle manifest, its ruleset, and the structure and effect sources it names."""

   def __init__(self, battle: Document, ruleset: Document, structure: Document,
                effects: dict[str, SourceDocument] | None = None) -> None:
      """!Wraps the Documents.
      @param battle     Document (capsule.battle/1) with a path
      @param ruleset    Document (capsule.ruleset/2) with a path
      @param structure  Document (capsule.structure/1) with a path: the structure manifest the battle names
      @param effects    {path as the manifest names it: SourceDocument with a path}, in manifest order
      """
      docs = [battle, ruleset, structure] + list((effects or {}).values())
      if any(d.path is None for d in docs):
         raise DocumentError("battle data needs files (save them first)")
      ## The battle manifest (the content).
      self.battle = battle
      ## The ruleset.
      self.ruleset = ruleset
      ## The structure manifest (capsule.structure/1).
      self.structure = structure
      # One edit of either manifest may change both (a rename walks both): one undo step (core.document partners).
      battle.partners = [structure]
      structure.partners = [battle]
      ## The effect sources: {path relative to the battle manifest (as it lists them): SourceDocument}.
      self.effects = dict(effects or {})
      ## The bench scenarios opened as Documents (core.bench; the Bench page, renames that follow them) by file:
      ## unsaved ones count in dirty and save_all() writes them [S14].
      self.scenarios: dict[Path, Document] = {}
      ## Last compile per platform: {platform or None: (revisions, compiled or None, error or None)}.
      self._cache = {}
      # Renames on these Documents follow the effect sources; source edits join the manifest's undo step.
      logic.attach(self)

   @classmethod
   def open(cls, path: str | Path) -> BattleProject:
      """!Opens a battle manifest and the files it names: its ruleset, its
      structure manifest and its effect sources (a named file that does not
      exist yet starts empty; the next save writes it).
      @param path  battle.json
      @return BattleProject
      @throws NeedsSplit for a single-file manifest (split() migrates it)
      @throws DocumentError when it names no structure manifest or a file does not read
      """
      b = Document.open(path, BATTLE_SCHEMA)
      rel = b.data.get("ruleset")
      if not isinstance(rel, str):
         raise DocumentError(f"{path}: ruleset must name a {RULESET_SCHEMA} file")
      rp = (b.path.parent / rel).resolve()
      if rp.exists():
         r = Document.open(rp, RULESET_SCHEMA)
      else:   # missing: start one, and write it with the next save
         r = Document(new_ruleset(), rp, RULESET_SCHEMA)
         r.dirty = True
      if b.data.get(STRUCTURE_KEY) is None:
         inline = [k for k in structure_keys() if k in b.data]
         if inline:
            raise NeedsSplit(b.path, inline)
         raise DocumentError(f"{path}: {STRUCTURE_KEY} must name a {STRUCTURE_SCHEMA} file")
      structure = _open_or_start(_named_file(b, b.data[STRUCTURE_KEY], STRUCTURE_KEY), STRUCTURE_SCHEMA)
      listed = b.data.get(EFFECTS_KEY, [])
      if not isinstance(listed, list):
         raise DocumentError(f"{path}: {EFFECTS_KEY} must list effect sources (paths ending in {EFFECT_SUFFIX})")
      effects = {}
      for rel_source in listed:
         sp = _named_file(b, rel_source, EFFECTS_KEY)
         if not rel_source.endswith(EFFECT_SUFFIX):
            raise DocumentError(f"{path}: effect sources end in {EFFECT_SUFFIX}, got {rel_source!r}")
         if rel_source in effects:
            raise DocumentError(f"{path}: {rel_source} is listed twice")
         if sp.exists():
            effects[rel_source] = SourceDocument.open(sp)
         else:   # listed but not written yet: an empty source, written with the next save
            effects[rel_source] = SourceDocument("", sp)
            effects[rel_source].dirty = True
      return cls(b, r, structure, effects)

   @classmethod
   def create(cls, path: str | Path, name: str = "battle") -> BattleProject:
      """!Starts new battle data from the Blank template (blank_template()): battle.json, structure.json and
      ruleset.json, written at once (editor.template records the template, as applying it does).
      @param path  battle.json to create
      @param name  id
      @return BattleProject
      """
      p = Path(path)
      rp = p.parent / RULESET_FILE
      sp = p.parent / STRUCTURE_FILE
      for f in (p, sp, rp):
         if f.exists():
            raise DocumentError(f"{f} already exists")
      p.parent.mkdir(parents=True, exist_ok=True)
      b = Document(new_battle(), p, BATTLE_SCHEMA)
      b.data["id"] = name
      st = Document(new_structure(), sp, STRUCTURE_SCHEMA)
      r = Document(new_ruleset(), rp, RULESET_SCHEMA)
      for doc in (st, r, b):
         doc.save()
      return cls(b, r, st)

   def documents(self) -> list[Document]:
      """!Every document: the battle manifest, the ruleset, the structure manifest, the effect sources.
      @return list of Documents
      """
      return [self.battle, self.ruleset, self.structure] + list(self.effects.values())

   def effect_source(self, rel: str) -> SourceDocument:
      """!An effect source by the path the manifest lists it under.
      @param rel  e.g. "effects/moves.ceffect"
      @return SourceDocument
      @throws DocumentError when the manifest lists no such source
      """
      sources = self.effects   # local name for "in": Doxygen 1.12 misreads "in self.x"
      if rel not in sources:
         raise DocumentError(f"no effect source {rel!r} (sources: {', '.join(sources) or 'none'})")
      return sources[rel]

   def scenario(self, path: str | Path) -> Document:
      """!A bench scenario as a Document, opened once and kept (its undo history and unsaved changes live as long
      as the project; core.bench.open_scenario()).
      @param path  the scenario file
      @return Document (schema capsule.bench/1)
      @throws DocumentError when the file is not a scenario
      """
      from . import bench   # local: core.bench imports this module
      key = Path(path).resolve()
      opened = self.scenarios   # local name for "in": Doxygen 1.12 misreads "in self.x"
      if key not in opened:
         opened[key] = bench.open_scenario(key)
      return opened[key]

   def edited_documents(self) -> list[Document]:
      """!Every Document with unsaved changes the user may have made: documents() and the open bench scenarios.
      @return list of Documents
      """
      return self.documents() + list(self.scenarios.values())

   @property
   def dirty(self) -> bool:
      """!Whether a document (or an open bench scenario) has unsaved changes.
      @return True when one has
      """
      return any(d.dirty for d in self.edited_documents())

   def save_all(self) -> None:
      """!Saves the documents (and the open bench scenarios) with changes.
      @return None
      """
      for d in self.edited_documents():
         if d.dirty:
            d.save()

   # -- names -----------------------------------------------------------------------

   def names(self, kind: str) -> list[str]:
      """!Entry names of a list, in order.
      @param kind  one of KINDS
      @return list of names
      """
      return [e.get("name", "?") for e in data_of(self.battle, kind).get(kind, []) if isinstance(e, dict)]

   def entry(self, kind: str, name: str) -> JsonDict:
      """!An entry by name.
      @param kind  one of KINDS
      @param name  its name
      @return the dict (live; change it only inside battle.edit())
      """
      return entry(self.battle, kind, name)

   def growth_names(self) -> list[str]:
      """!Growth tables (the structure manifest's "growth").
      @return list of names
      """
      return list((self.structure.data.get("growth") or {}).keys())

   # -- compiling -------------------------------------------------------------------

   def _revisions(self) -> tuple[int, ...]:
      """!Every document's revision.
      @return tuple
      """
      return tuple(d.revision for d in self.documents())

   def sources(self) -> dict[Path, JsonDict | str]:
      """!What the battle compiler reads in place of the files, so unsaved edits are compiled: the
      manifests' data and the effect sources' text by path.
      @return {absolute Path: parsed JSON, or a .ceffect source's text}
      """
      out: dict[Path, JsonDict | str] = {self.battle.path: self.battle.data, self.ruleset.path: self.ruleset.data,
                                         self.structure.path: self.structure.data}
      for source in self.effects.values():
         out[source.path] = source.text
      return out

   def compile(self, platform: str | None = None) -> tuple[JsonDict | None, str | None]:
      """!Compiles with the engine's battle compiler (cached until an edit).
      @param platform  target platform whose engine limits apply (the engine's build_settings.PLATFORMS), or
                       None for the engine's default (the GBA's, the strictest)
      @return (compiled dict or None, error message or None)
      """
      revs = self._revisions()
      cache = self._cache   # local name for .get(): Doxygen 1.12 misreads re-assigned members
      cached_revs, cached_compiled, cached_error = cache.get(platform, (None, None, None))
      if cached_revs == revs:
         return cached_compiled, cached_error
      sources = self.sources()
      try:
         bc = engine.tool("battle_compiler")
         compiled, error = bc.compile_battle(self.battle.path, None, sources, platform=platform,
                                             **self.scripts_option(bc)), None
      except Exception as e:   # the compiler's ManifestErrors, plus key/type errors in odd data
         compiled, error = None, str(e)
      cache[platform] = (revs, compiled, error)
      return compiled, error

   def error_now(self) -> str | None:
      """!Compiles what the Documents hold right now, without the cache: inside an edit() block the revisions have
      not moved yet, so compile() would answer for the data as it was before the block.
      @return error message, or None when the data compiles
      """
      try:
         bc = engine.tool("battle_compiler")
         bc.compile_battle(self.battle.path, None, self.sources(), **self.scripts_option(bc))
      except Exception as e:   # as compile()
         return str(e)
      return None

   def scripts_manifest(self) -> Path | None:
      """!The game's scripts manifest (its reference/project.json "scripts"), whose field placeholders ({player})
      the battle's in-game texts may use (E7).
      @return the file, or None outside a game or without one
      """
      from . import codepage, project as projects   # local: core.codepage imports this module
      found = codepage.find_project(self.battle.path) if self.battle.path is not None else None
      if found is None:
         return None
      try:
         path = projects.game_files(codepage.open_project(found)).get(SCRIPTS_FILE_KEY)
      except (DocumentError, OSError, ValueError):
         return None
      return path if path is not None and path.is_file() else None

   def scripts_option(self, bc: Any) -> dict[str, Any]:
      """!The compile_battle() keyword naming the game's scripts manifest (E7's `scripts=`), when the engine takes
      it and the game has one.
      @param bc  the battle compiler module
      @return {"scripts": path} or {}
      """
      if "scripts" not in inspect.signature(bc.compile_battle).parameters:
         return {}
      path = self.scripts_manifest()
      return {"scripts": path} if path is not None else {}

   def validate(self, platform: str | None = None) -> str | None:
      """!Compiles and reports.
      @param platform  target platform whose limits apply, or None for the engine's default (see compile())
      @return error message, or None when the data compiles
      """
      return self.compile(platform)[1]

   def targets(self) -> list[str]:
      """!The platforms the game builds for (its reference/project.json "targets",
      core.structure.stats.project_targets()).
      @return platform names
      @throws DocumentError when the project lists a platform the engine does not know
      """
      from .structure import stats   # local: core.structure.stats imports this module
      return stats.project_targets(self.battle.path)

   def target_errors(self, targets: list[str] | None = None) -> list[str]:
      """!Compiles for each platform the game builds for and reports each one that fails.
      @param targets  platforms, or None for the game's targets (targets())
      @return one "platform: error" per platform the data does not compile for (empty when it compiles for all)
      """
      try:
         chosen = list(targets) if targets is not None else self.targets()
      except DocumentError as e:   # a project.json naming an unknown platform
         return [str(e)]
      out = []
      for platform in chosen:
         error = self.validate(platform)
         if error:
            out.append(f"{platform}: {error}")
      return out

   def validate_targets(self, targets: list[str] | None = None) -> str | None:
      """!Compiles for every platform the game builds for (what a save checks).
      @param targets  platforms, or None for the game's targets (targets())
      @return the errors, each naming its platform ("gba: ..."; several joined by "; "), or None when the data
              compiles for every target
      """
      errors = self.target_errors(targets)
      return "; ".join(errors) if errors else None

   def ruleset_report(self) -> tuple[list[FormulaRow], str | None]:
      """!The ruleset alone: every formula's analysed and declared range (the formula slots, the named
      formulas, then the stat formulas).
      @return (list of (slot, bounds, range, clamp_active, expr), error or None)
      """
      try:
         rc = engine.tool("ruleset_compiler")
         data = engine.tool("battle_compiler").strip(self.ruleset.data)
         compiled = rc.load(data, self.ruleset.path.name)
      except Exception as e:
         return [], str(e)
      formulas = list(compiled["formulas"].items()) + list(compiled.get("stat_formulas", {}).items())
      rows = [(slot, f["bounds"], f["range"], f["clamp_active"], f["expr"]) for slot, f in formulas]
      return rows, None

   def formula_slots(self) -> list[str]:
      """!Every formula the ruleset has or can have: the engine's formula slots, the ruleset's named formulas
      (pipelines call them), then its stat formulas (the battle's stats name them).
      @return list of names
      """
      rc = engine.tool("ruleset_compiler")
      named = named_formulas(self.ruleset)
      return list(rc.FORMULA_SLOTS) + named + [n for n in stat_formulas(self.ruleset)
                                                if n not in rc.FORMULA_SLOTS and n not in named]

   def _input_names(self, slot: str) -> list[str]:
      """!The inputs a formula takes.
      @param slot  formula slot, named formula or stat formula name
      @return input names
      @throws KeyError when there is no such formula
      """
      rc = engine.tool("ruleset_compiler")
      if slot in rc.FORMULA_SLOTS:
         return list(rc.FORMULA_SLOTS[slot])
      if slot in named_formulas(self.ruleset):
         args = formula_entry(self.ruleset, slot).get("args")
         return [a for a in args if isinstance(a, str)] if isinstance(args, list) else []
      if slot in stat_formulas(self.ruleset):
         return list(rc.STAT_INPUTS)
      raise KeyError(slot)

   def formula(self, slot: str, **inputs: int) -> int:
      """!Evaluates one ruleset formula as the generated C++ would (clamp included).
      @param slot    formula slot, named formula or stat formula
      @param inputs  input values
      @return int
      @throws DocumentError when the ruleset does not compile or an input is missing
      """
      rc = engine.tool("ruleset_compiler")
      data = engine.tool("battle_compiler").strip(self.ruleset.data)
      try:
         compiled = rc.load(data, self.ruleset.path.name)
         missing = [n for n in self._input_names(slot) if n not in inputs]
         if missing:
            raise DocumentError(f"{slot} needs {', '.join(missing)}")
         return rc.run(compiled, slot, **inputs)
      except rc.RulesetError as e:
         raise DocumentError(str(e)) from None
      except KeyError:
         raise DocumentError(f"unknown formula {slot!r}") from None

   def formula_inputs(self, slot: str) -> list[tuple[str, tuple[int, ...] | None]]:
      """!The inputs a formula takes, with their declared ranges.
      @param slot  slot, named formula or stat formula name
      @return list of (name, (lo, hi) or None); [] for an unknown formula
      """
      ranges = self.ruleset.data.get("inputs") or {}
      try:
         names = self._input_names(slot)
      except KeyError:
         return []
      return [(n, tuple(ranges[n]) if n in ranges else None) for n in names]

   def stats(self, species: str, level: int, genes: list[int] | None = None, training: list[int] | None = None,
             trait: str | None = None, awaken: list[int] | None = None) -> list[int]:
      """!A creature's stats as the engine computes them.
      @param species   species name
      @param level     level (1 to the rules' level_max)
      @param genes     one gene per stat (default 0; each within the layout's stat_genes width)
      @param training  one training value per stat (default 0; the layout's stat_training width)
      @param trait     trait name, or None
      @param awaken    one awakening value per stat (default 0; the layout's stat_awaken width)
      @return one value per stat (stat_keys(battle) order)
      @throws DocumentError when the data does not compile, the species is unknown or a value is out of the
              range the data gives it (S11: the level from rules.level_max, the rest from the layout's widths)
      """
      compiled, error = self.compile()
      if compiled is None:
         raise DocumentError(error)
      if species not in [s["name"] for s in compiled["species"]]:
         raise DocumentError(f"no species {species!r}")
      if trait is not None and trait not in compiled["names"]["traits"]:
         raise DocumentError(f"no trait {trait!r}")
      check_level(self.structure, level)
      from .structure import record   # local: core.structure.record imports this module
      record.check_stat_inputs(self.battle, {"gene": genes, "training": training, "awaken": awaken})
      bc = engine.tool("battle_compiler")
      return bc.preview_stats(compiled, species, level, genes, training, awaken, trait)

   def files(self) -> list[Path]:
      """!Every file the battle data is built from: the manifest, its ruleset
      and what they name (presenter sequences), as the engine's depfile lists
      them. Copy these to move the data elsewhere.
      @return list of absolute Paths (the ruleset even while it is not written yet)
      @throws DocumentError when the data does not compile
      """
      deps: list[Path] = []
      sources = self.sources()
      try:
         bc = engine.tool("battle_compiler")
         bc.compile_battle(self.battle.path, deps, sources, **self.scripts_option(bc))
      except Exception as e:   # the compiler's ManifestErrors, plus key/type errors in odd data
         raise DocumentError(str(e)) from None
      out = []
      # The documents too: a ruleset or source not written yet is a file of the data all the same.
      for d in deps + [doc.path for doc in self.documents()]:
         if d not in out:
            out.append(d)
      return out


def stat_keys(doc: Document | None = None) -> list[str]:
   """!The stats a creature has, in record order: the structure manifest's "stats" (D-20 C).
   @param doc  a manifest Document of the battle (part_of()), or None for the stats of new battle data (NEW_STRUCTURE)
   @return list of names ("hp", "attack", ...)
   """
   given = (data_of(doc, "stats") if doc is not None else NEW_STRUCTURE).get("stats")
   return [st["name"] for st in given if isinstance(st, dict) and isinstance(st.get("name"), str)] \
       if isinstance(given, list) else []


def party_max(doc: Document | None = None) -> int:
   """!Most members a party holds: the record layout's party_size (core.structure.record.party_size()).
   @param doc  a manifest Document of the battle, or None for new battle data (the engine's default party size)
   @return count
   """
   if doc is None:
      return engine.tool("battle_compiler").PARTY_SIZE
   from .structure import record   # local: core.structure.record imports this module
   return record.party_size(doc)


def _rule(doc: Document | None, key: str, default: int, lo: int, hi: int) -> int:
   """!An integer of the structure's rules as the battle compiler takes it: the value when it is one the compiler
   accepts, else the compiler's default.
   @param doc      a manifest Document of the battle, or None (the default)
   @param key      the rules key
   @param default  the compiler's default
   @param lo       lowest value the compiler accepts
   @param hi       highest value the compiler accepts
   @return the value
   """
   rules = data_of(doc, "rules").get("rules") if doc is not None else None
   value = rules.get(key, default) if isinstance(rules, dict) else default
   ok = isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi
   return value if ok else default


def level_max(doc: Document | None = None) -> int:
   """!The data's highest level (rules.level_max, within the battle compiler's MIN_LEVEL_MAX..MAX_LEVEL_MAX; its
   DEFAULT_LEVEL_MAX when the rules give no usable one): levels run from 1 to it.
   @param doc  a manifest Document of the battle, or None for the compiler's default
   @return the level
   """
   bc = engine.tool("battle_compiler")
   return _rule(doc, "level_max", bc.DEFAULT_LEVEL_MAX, bc.MIN_LEVEL_MAX, bc.MAX_LEVEL_MAX)


def rank_max(doc: Document | None = None) -> int:
   """!The data's highest party rank (rules.rank_max, a byte; the compiler's DEFAULT_RANK_MAX when the rules give
   no usable one): ranks run from 0 to it.
   @param doc  a manifest Document of the battle, or None for the compiler's default
   @return the rank
   """
   bc = engine.tool("battle_compiler")
   return _rule(doc, "rank_max", bc.DEFAULT_RANK_MAX, 0, bc.U8_MAX)


def check_level(doc: Document | None, level: Any, what: str = "level") -> int:
   """!A level the data takes (1 to level_max()).
   @param doc    a manifest Document of the battle, or None
   @param level  the value
   @param what   what it is, for the message
   @return the level
   @throws DocumentError for another value
   """
   most = level_max(doc)
   if not isinstance(level, int) or isinstance(level, bool) or not 1 <= level <= most:
      raise DocumentError(f"{what}: 1 to {most} (rules.level_max), got {level!r}")
   return level


def presenters_max() -> int:
   """!Most presenters a party shows (the engine's kMaxPresenters).
   @return count
   """
   return engine.tool("battle_compiler").MAX_PRESENTERS


# -- editing helpers (inside doc.edit()) ---------------------------------------------------

def entries(doc: Document, kind: str) -> list[JsonDict]:
   """!A list of the battle data, from the manifest holding it (part_of(): categories, statuses, weathers and
   formats are the structure manifest's).
   @param doc   a manifest Document of the battle
   @param kind  one of KINDS
   @return the list (created when absent)
   """
   if kind not in KINDS:
      raise DocumentError(f"unknown kind {kind!r} (kinds: {', '.join(KINDS)})")
   return data_of(doc, kind).setdefault(kind, [])


def entry(doc: Document, kind: str, name: str) -> JsonDict:
   """!An entry by name.
   @param doc   battle Document
   @param kind  one of KINDS
   @param name  entry name
   @return the dict
   """
   for e in entries(doc, kind):
      if isinstance(e, dict) and e.get("name") == name:
         return e
   raise DocumentError(f"no {SINGULAR.get(kind, kind)} {name!r}")


def unique_name(doc: Document, kind: str, base: str) -> str:
   """!A name not used in a list.
   @param doc   battle Document
   @param kind  one of KINDS
   @param base  wanted name
   @return base, or "base 2", "base 3", ...
   """
   names = {e.get("name") for e in entries(doc, kind) if isinstance(e, dict)}
   if base not in names:
      return base
   n = FIRST_COPY_NUMBER
   while f"{base} {n}" in names:
      n += 1
   return f"{base} {n}"


def move_base_fields(doc: Document) -> list[str]:
   """!The move fields the move resources read (each resource's "base"), in resource order.
   @param doc  a manifest Document of the battle
   @return field names
   """
   given = data_of(doc, "resources").get("resources")
   rows = given if isinstance(given, list) else []
   return [r["base"] for r in rows
           if isinstance(r, dict) and r.get("scope") == "move" and isinstance(r.get("base"), str)]


def add_entry(doc: Document, kind: str, name: str, copy_of: str | None = None, unique: bool = False) -> str:
   """!Adds an entry (a copy of another, or the kind's template).
   @param doc      battle Document
   @param kind     one of KINDS
   @param name     its name (refused when taken), or with @p unique the wanted name
   @param copy_of  name of an entry to copy, or None
   @param unique   True to number a taken name ("base 2", unique_name(): a page's Copy), False to refuse it
   @return the name used
   @throws DocumentError for an empty or (without @p unique) taken name
   """
   if not isinstance(name, str) or not name.strip():
      raise DocumentError("names can't be empty")
   name = name.strip()
   if unique:
      name = unique_name(doc, kind, name)
   elif name in [e.get("name") for e in entries(doc, kind) if isinstance(e, dict)]:
      raise DocumentError(f"there is already a {SINGULAR.get(kind, kind)} {name!r}")
   if copy_of is not None:
      e = copy.deepcopy(entry(doc, kind, copy_of))
   else:
      e = copy.deepcopy(NEW_ENTRY[kind])
      types = [t.get("name") for t in entries(doc, "types")]
      first_type = types[0] if types else NEW_BATTLE["types"][0]["name"]

      # New moves and species start with the first type, category and growth table (the templates leave
      # them unset), and one base value per stat.
      if kind == "moves":
         e["type"] = first_type
         categories = [c.get("name") for c in entries(doc, "categories")]
         e["category"] = categories[0] if categories else NEW_STRUCTURE["categories"][0]["name"]
         if isinstance(data_of(doc, BY_TYPE_KEY).get(BY_TYPE_KEY), dict):
            del e["category"]   # category_by_type: a new (damaging) move takes its type's
         # every move states its base of each move resource (D-25: no default)
         for field in move_base_fields(doc):
            e[field] = NEW_RESOURCE_BASE
      elif kind == "species":
         e["types"] = [first_type]
         growth = list((data_of(doc, "growth").get("growth") or {}).keys())
         e["growth"] = growth[0] if growth else next(iter(NEW_STRUCTURE["growth"]))
         e["base"] = [NEW_BASE_STAT] * len(stat_keys(doc))
      elif kind == "parties":
         # the AI profile of the data's first party (the game's usual choice), else none (the default profile; G1)
         first = next((t for t in entries(doc, "parties") if isinstance(t, dict)), None)
         ai = first.get("ai") if first is not None else None
         if isinstance(ai, str):
            e["ai"] = ai
   e["name"] = name
   entries(doc, kind).append(e)
   if kind == "types":
      from .structure import categories   # local: core.structure imports this module
      categories.type_added(doc, name)   # category_by_type names every type
   return name


## The effect compiler's structure list naming each kind's entries (effect code names them; core.logic).
LOGIC_LISTS = {"types": "types", "categories": "categories", "moves": "moves", "species": "species",
               "passives": "passives", "items": "items", "statuses": "statuses", "weathers": "weathers"}


def references(doc: Document, kind: str, name: str, new: str | None = None) -> list[str]:
   """!Finds (and optionally renames) every reference to an entry: the manifests' fields and the effect logic
   (core.logic.references(): the sources of the project the Document belongs to, the manifests' point handler
   code; an entry's own logic block counts, and is renamed with it).
   @param doc   a manifest Document of the battle (both manifests are walked: chart, rules and the condition
                records are structure)
   @param kind  one of KINDS
   @param name  entry name
   @param new   new name to write, or None to only look
   @return list of "where" strings
   @throws DocumentError when an effect source does not parse (a rename could not follow it)
   """
   d = merged(doc)
   found = []

   def fix(container: JsonDict, key: str, label: str) -> None:
      """!Records (and renames) a field holding the name.
      @param container  dict holding the field
      @param key        field name
      @param label      "where" string to record
      """
      if isinstance(container, dict) and container.get(key) == name:
         found.append(label)
         if new is not None:
            container[key] = new

   def fix_list(lst: list[Any] | None, label: str) -> None:
      """!Records (and renames) the items of a list equal to the name.
      @param lst    list, or None
      @param label  "where" string to record
      """
      for i, v in enumerate(lst if isinstance(lst, list) else []):
         if v == name:
            found.append(label)
            if new is not None:
               lst[i] = new

   def members() -> list[tuple[str, JsonDict]]:
      """!Every party member, with its "where" label.
      @return list of (label, member dict)
      """
      return [(f"party {t.get('name')}", m) for t in d.get("parties", []) if isinstance(t, dict)
              for m in t.get("members", []) if isinstance(m, dict)]

   if kind == "types":
      for m in d.get("moves", []):
         fix(m, "type", f"move {m.get('name')}")
      for s in d.get("species", []):
         fix_list(s.get("types"), f"species {s.get('name')}")
         for f in s.get("forms", []) if isinstance(s.get("forms"), list) else []:   # G4: a form's own types
            if isinstance(f, dict):
               fix_list(f.get("types"), f"species {s.get('name')} form {f.get('name')}")
      for st in d.get("statuses", []):
         fix_list(st.get("immune_types"), f"status {st.get('name')}")
         fix(st, "thawed_by_hit", f"status {st.get('name')}")
      for w in d.get("weathers", []):
         fix_list(w.get("immune_types"), f"weather {w.get('name')}")
      # The type chart's matchups name types as row (attacker) and column (defender) keys.
      from .structure import chart   # local: core.structure.chart imports this module
      if chart.rename_type(d, name, new):
         found.append("chart")
      # category_by_type (E11) and the hit types' categories (C5) name every type as a key: the key follows, in
      # its place
      for key in type_tables():
         rule = d.get(key)
         if isinstance(rule, dict) and name in rule:
            found.append(key)
            if new is not None:
               renamed = [(new if t == name else t, c) for t, c in rule.items()]
               rule.clear()
               rule.update(renamed)
   elif kind == "categories":
      for m in d.get("moves", []):
         fix(m, "category", f"move {m.get('name')}")
      fix((d.get("rules") or {}).get("self_hit"), "category", "rules.self_hit.category")
      for key in type_tables():
         rule = d.get(key)
         for t in list(rule) if isinstance(rule, dict) else []:
            fix(rule, t, f"{key} {t}")
   elif kind == "moves":
      for s in d.get("species", []):
         for le in s.get("learnset", []):
            if isinstance(le, list) and len(le) == LEARNSET_ENTRY_LENGTH and le[1] == name:
               found.append(f"species {s.get('name')} learnset")
               if new is not None:
                  le[1] = new
      for label, m in members():
         fix_list(m.get("moves"), label)
      fix(d.get("rules") or {}, "fallback_move", "rules.fallback_move")
      for s in d.get("species", []):   # C6: the species' teachable moves
         fix_list(s.get(TEACHABLE_KEY), f"species {s.get('name')} teachable")
      for s in d.get("species", []):   # B1: the species' combine moves
         fix_list(s.get(COMBINE_MOVES_KEY), f"species {s.get('name')} combine_moves")
   elif kind == "species":
      for label, m in members():
         fix(m, "species", label)
      # G4: the species' transformation rules name species (into / also)
      from . import species_growth   # local: core.species_growth imports this module
      species_growth.follow_species_rename(d, name, new, found)
   elif kind == "passives":
      for s in d.get("species", []):
         fix_list(s.get("passives"), f"species {s.get('name')}")
         for f in s.get("forms", []) if isinstance(s.get("forms"), list) else []:   # G4: a form's own passives
            if isinstance(f, dict):
               fix_list(f.get("passives"), f"species {s.get('name')} form {f.get('name')}")
   elif kind == "items":
      for label, m in members():
         fix(m, "item", label)
      # G2: the shop lists (battle.json "shops") name items
      for sh in d.get("shops", []) if isinstance(d.get("shops"), list) else []:
         if isinstance(sh, dict):
            fix_list(sh.get("items"), f"shop {sh.get('name')}")
      # G4: the growth rules' expressions name items by their word (item == bloom_charm)
      from . import species_growth   # local: core.species_growth imports this module
      species_growth.follow_item_rename(d, name, new, found)
      # G3: a party's bag (its "items", the AI's item-use rules) and the profiles' item-use rules name items
      for t in d.get("parties", []):
         if isinstance(t, dict):
            fix_list(t.get("items"), f"party {t.get('name')} items")
      from . import ai   # local: core.ai imports this module
      ai.follow_item_rename(doc, name, new, found)
   elif kind == "traits":
      for label, m in members():
         fix(m, "trait", label)
   elif kind == "presenters":
      for t in d.get("parties", []):
         if isinstance(t, dict):
            fix_list(t.get("presenters"), f"party {t.get('name')}")
   if kind == "statuses":
      # G3: the recruit section's status bonuses name statuses
      from .structure import recruit   # local: core.structure.recruit imports this module
      if recruit.follow_status_rename(doc, name, new):
         found.append("recruit: status_bonus")
   # C8: the field rules' expressions (lead rules, field action requirements) read moves (knows.MOVE), passives
   # (passive.NAME) and items (item.NAME): a rename follows them, a removal is refused while they read the entry
   from .structure import field_expressions   # local: core.structure imports this module
   followers = {"moves": field_expressions.follow_move, "passives": field_expressions.follow_passive,
                "items": field_expressions.follow_item}
   if kind in followers:
      found += followers[kind](d, name, new)
   # B1: the combination methods' recipes, results, type tables and sp.NAME / type.NAME words
   from .structure import combination   # local: core.structure imports this module
   found += combination.follow_entry(d, kind, name, new)
   if kind in LOGIC_LISTS:
      found += logic.references(doc, (LOGIC_LISTS[kind],), name, new)
   return found


def rename_entry(doc: Document, kind: str, old: str, new: str) -> int:
   """!Renames an entry and every reference to it: the manifests, the effect logic and the game's bench scenarios
   (core.bench.follow_rename(): edited as the project's scenario Documents, in the same undo step).
   @param doc   battle Document
   @param kind  one of KINDS
   @param old   current name
   @param new   new name
   @return number of references updated
   """
   if not isinstance(new, str) or not new.strip():
      raise DocumentError("names can't be empty")
   new = new.strip()
   if new == old:
      return 0
   if new in [e.get("name") for e in entries(doc, kind) if isinstance(e, dict)]:
      raise DocumentError(f"there is already a {SINGULAR[kind]} {new!r}")
   e = entry(doc, kind, old)
   n = len(references(doc, kind, old, new))
   if kind not in LOGIC_LISTS:   # the others follow the bench scenarios with the effect logic (core.logic)
      from . import bench   # local: core.bench imports this module
      n += len(bench.follow_rename(logic.project_of(doc), kind, old, new, "Rename " + SINGULAR[kind]))
   e["name"] = new
   return n


def remove_entry(doc: Document, kind: str, name: str) -> None:
   """!Removes an entry nothing refers to (refused too when the ruleset no longer binds without it:
   check_ruleset_kept()).
   @param doc   battle Document
   @param kind  one of KINDS
   @param name  entry name
   @return None
   """
   e = entry(doc, kind, name)
   # chart cells and the type's category_by_type / hit types' entries go with the type
   tables = type_tables()
   refs = [r for r in references(doc, kind, name) if kind != "types" or r not in ["chart", *tables]]
   if refs:
      shown = ", ".join(sorted(set(refs))[:REFERENCES_SHOWN])
      raise DocumentError(f"{SINGULAR[kind]} {name!r} is still used by: {shown}")
   before = ruleset_problem(doc)
   if kind == "types":
      from .structure import chart   # local: see references()
      chart.drop_type(data_of(doc, chart.CHART_KEY), name)
      for key in tables:
         rule = data_of(doc, key).get(key)
         if isinstance(rule, dict):
            rule.pop(name, None)
   entries(doc, kind).remove(e)
   check_ruleset_kept(doc, f"{SINGULAR[kind]} {name!r}", before)


def move_entry(doc: Document, kind: str, name: str, delta: int) -> bool:
   """!Moves an entry up or down its list (order = engine index). A category move keeps every move's category
   (core.structure.categories.keep_default()).
   @param doc    battle Document
   @param kind   one of KINDS
   @param name   entry name
   @param delta  -1 up, +1 down
   @return True if it moved
   """
   lst = entries(doc, kind)
   e = entry(doc, kind, name)
   i = lst.index(e)
   j = i + delta
   if not 0 <= j < len(lst):
      return False
   first = lst[0].get("name") if isinstance(lst[0], dict) else None
   lst[i], lst[j] = lst[j], lst[i]
   if kind == "categories":
      from .structure import categories   # local: core.structure imports this module
      categories.keep_default(doc, first)
   return True


def set_field(doc: Document, kind: str, name: str, key: str, value: Any, keep_null: bool = False) -> None:
   """!Sets (or with None removes) one field of an entry. The compiler
   checks values; editors show its message.
   @param doc        battle Document
   @param kind       one of KINDS
   @param name       entry name
   @param key        field name (not "name": use rename_entry)
   @param value      JSON value, or None to remove the field
   @param keep_null  store None as JSON null instead of removing the field
                     (a move's "accuracy": null means it never misses)
   @return None
   """
   if key == "name":
      raise DocumentError("use rename to change a name")
   e = entry(doc, kind, name)
   if value is None and not keep_null:
      e.pop(key, None)
   else:
      e[key] = copy.deepcopy(value)
   if kind == "traits":
      with_trait_pct(e)


## Keys of a trait naming the stats it raises and lowers (with them the engine wants "pct", E7).
TRAIT_STAT_KEYS = ("up", "down")
## A trait's percentages [raised %, lowered %].
TRAIT_PCT_KEY = "pct"


def with_trait_pct(trait: JsonDict) -> JsonDict:
   """!Gives a trait that raises or lowers a stat its "pct" when it has none (E7: no default percentages): the
   engine's unchanged percentage for both, which the game then sets (the compiler accepts it, the stat stays).
   @param trait  a trait entry (changed in place)
   @return the entry
   """
   if isinstance(trait, dict) and any(k in trait for k in TRAIT_STAT_KEYS) and TRAIT_PCT_KEY not in trait:
      unchanged = int(engine.tool("battle_compiler").PERCENT)
      trait[TRAIT_PCT_KEY] = [unchanged] * len(TRAIT_STAT_KEYS)
   return trait


def chart_value(doc: Document, attacker: str, defender: str) -> Any:
   """!A type chart cell (core.structure.chart.matchup()).
   @param doc       battle Document
   @param attacker  type name
   @param defender  type name
   @return the tier's name (the default tier when the cell is not given)
   """
   from .structure import chart   # local: see references()
   return chart.matchup(doc, attacker, defender)


def set_chart(doc: Document, attacker: str, defender: str, value: Any) -> None:
   """!Sets a type chart cell (core.structure.chart.set_matchup(); the default tier leaves it out).
   @param doc       battle Document
   @param attacker  type name
   @param defender  type name
   @param value     a tier name, or a multiplier equal to one tier's factor (0: the zero tier)
   @return None
   """
   from .structure import chart   # local: see references()
   chart.set_matchup(doc, attacker, defender, value)


def learn(doc: Document, species: str, level: int, move: str) -> None:
   """!Adds a learnset entry (kept sorted by level).
   @param doc      battle Document
   @param species  species name
   @param level    level
   @param move     move name
   @return None
   """
   if move not in [m.get("name") for m in entries(doc, "moves")]:
      raise DocumentError(f"no move {move!r}")
   check_level(doc, level)
   s = entry(doc, "species", species)
   ls = s.setdefault("learnset", [])
   if [level, move] in ls:
      raise DocumentError(f"{species} already learns {move} at {level}")
   ls.append([int(level), move])
   ls.sort(key=lambda x: x[0])


def teachable(doc: Document, species: str) -> list[str] | None:
   """!The moves `teach` may give a species (C6; engine species `teachable`).
   @param doc      battle Document
   @param species  species name
   @return the move names, or None when the species lists none (any move while no species lists any)
   """
   given = entry(doc, "species", species).get(TEACHABLE_KEY)
   return list(given) if isinstance(given, list) else None


def set_teachable(doc: Document, species: str, move: str, on: bool) -> bool:
   """!Adds a move to a species' teachable list or takes it out (an empty list goes: once any species lists
   teachable moves, a species without the key learns none by `teach`).
   @param doc      battle Document
   @param species  species name
   @param move     move name
   @param on       add (True) or remove
   @return True when the list changed
   """
   if move not in [m.get("name") for m in entries(doc, "moves")]:
      raise DocumentError(f"no move {move!r}")
   s = entry(doc, "species", species)
   given = list(s.get(TEACHABLE_KEY) or [])
   if on == (move in given):
      return False
   given = given + [move] if on else [m for m in given if m != move]
   if given:
      s[TEACHABLE_KEY] = given
   else:
      s.pop(TEACHABLE_KEY, None)
   return True


def forget(doc: Document, species: str, move: str, level: int | None = None) -> int:
   """!Removes learnset entries of a move.
   @param doc      battle Document
   @param species  species name
   @param move     move name
   @param level    only this level, or None for all
   @return entries removed
   """
   s = entry(doc, "species", species)
   before = len(s.get("learnset", []))
   s["learnset"] = [le for le in s.get("learnset", [])
                    if not (le[1] == move and (level is None or le[0] == level))]
   return before - len(s["learnset"])


def party_add(doc: Document, party: str, species: str, level: int, **fields: Any) -> int:
   """!Adds a creature to a party's members.
   @param doc      battle Document
   @param party    party name
   @param species  species name
   @param level    level
   @param fields   moves, item, passive (slot), genes, trait
   @return its index
   """
   if species not in [s.get("name") for s in entries(doc, "species")]:
      raise DocumentError(f"no species {species!r}")
   t = entry(doc, "parties", party)
   members = t.setdefault("members", [])
   most = party_max(doc)
   if len(members) >= most:
      raise DocumentError(f"a party has at most {most} members (the record layout's party_size)")
   check_level(doc, level)
   if fields.get("genes") is not None:
      from .structure import record   # local: core.structure.record imports this module
      record.check_stat_inputs(doc, {"gene": [fields["genes"]]})
   pm = {"species": species, "level": int(level)}
   pm.update({k: v for k, v in fields.items() if v is not None})
   members.append(pm)
   return len(members) - 1


def party_remove(doc: Document, party: str, index: int) -> None:
   """!Removes a party member.
   @param doc    battle Document
   @param party  party name
   @param index  member index
   @return None
   """
   t = entry(doc, "parties", party)
   members = t.get("members", [])
   if not 0 <= index < len(members):
      raise DocumentError(f"{party} has no member {index}")
   del members[index]


def presenter_attach(doc: Document, party: str, presenter: str) -> None:
   """!Adds a presenter to the ones a party shows (in order: the first enters first).
   @param doc        battle Document
   @param party      party name
   @param presenter  presenter name
   @return None
   """
   entry(doc, "presenters", presenter)   # raises when there is none
   t = entry(doc, "parties", party)
   shown = t.setdefault("presenters", [])
   if presenter in shown:
      raise DocumentError(f"{party} already shows {presenter}")
   most = presenters_max()
   if len(shown) >= most:
      raise DocumentError(f"a party shows at most {most} presenters")
   shown.append(presenter)


def presenter_detach(doc: Document, party: str, presenter: str) -> None:
   """!Removes a presenter from the ones a party shows.
   @param doc        battle Document
   @param party      party name
   @param presenter  presenter name
   @return None
   """
   t = entry(doc, "parties", party)
   shown = t.get("presenters", [])
   if presenter not in shown:
      raise DocumentError(f"{party} does not show {presenter}")
   shown.remove(presenter)


# -- terms -----------------------------------------------------------------------------------------

def default_terms() -> dict[str, Term]:
   """!The engine's neutral word for every concept (the battle compiler's TERMS).
   @return {concept: {"one": word, "many": words}}, in the compiler's concept order
   """
   bc = engine.tool("battle_compiler")
   if hasattr(bc, "plural_of"):   # E7: the compiler's own plurals (irregular and invariant words)
      return {c: dict(v) for c, v in bc.compile_terms({}, "terms").items()}
   return {c: {"one": w, "many": w if c in bc.INVARIANT_TERMS else w + bc.PLURAL_SUFFIX} for c, w in bc.TERMS.items()}


## The terms section's plural rule key (battle_compiler.PLURAL_KEY, E7).
PLURAL_KEY = "plural"


def plural_rules() -> list[str]:
   """!The plural rules a terms section may name (battle_compiler.PLURAL_RULES; the first is the default).
   @return rule names ([] on an engine without them)
   """
   return list(getattr(engine.tool("battle_compiler"), "PLURAL_RULES", ()))


def plural_rule(doc: Document) -> str | None:
   """!The terms section's plural rule.
   @param doc  battle Document
   @return the rule it names, or None (the compiler's default)
   """
   t = data_of(doc, "terms").get("terms")
   rule = t.get(PLURAL_KEY) if isinstance(t, dict) else None
   return rule if isinstance(rule, str) else None


def set_plural_rule(doc: Document, rule: str | None) -> None:
   """!Sets the rule that derives a plural the game leaves out (None: the compiler's default).
   @param doc   battle Document
   @param rule  one of plural_rules(), or None
   @return None
   """
   rules = plural_rules()
   if rule is not None and rule not in rules:
      raise DocumentError(f"plural rules: {', '.join(rules) or 'none in this engine'}; got {rule!r}")
   t = data_of(doc, "terms").get("terms")
   if not isinstance(t, dict):
      t = data_of(doc, "terms")["terms"] = {}
   if rule is None:
      t.pop(PLURAL_KEY, None)
   else:
      t[PLURAL_KEY] = rule


def derived_plural(doc: Document, concept: str, one: str) -> str:
   """!The plural the battle compiler derives for a word the game gives without one (bc.plural_of() by the
   section's rule; the older engine's word + suffix).
   @param doc      battle Document
   @param concept  the concept
   @param one      its word
   @return the plural
   """
   bc = engine.tool("battle_compiler")
   if hasattr(bc, "plural_of"):
      return str(bc.plural_of(one, plural_rule(doc) or bc.DEFAULT_PLURAL_RULE))
   return one if concept in bc.INVARIANT_TERMS else one + bc.PLURAL_SUFFIX


def terms(doc: Document) -> dict[str, Term]:
   """!The game's words: the manifest's terms section merged over the engine's
   defaults (as the battle compiler merges them). A value the compiler would
   refuse is shown as the default; validate() reports it.
   @param doc  battle Document
   @return {concept: {"one": word, "many": words}} for every concept
   """
   out = default_terms()
   given = data_of(doc, "terms").get("terms")
   for concept, v in (given if isinstance(given, dict) else {}).items():
      if concept not in out:
         continue   # the plural rule, odd keys
      if isinstance(v, str):
         v = {"one": v}
      if not isinstance(v, dict) or not isinstance(v.get("one"), str):
         continue
      one = v["one"]
      many = v.get("many", derived_plural(doc, concept, one))
      if isinstance(many, str):
         out[concept] = {"one": one, "many": many}
   return out


def term(doc: Document, concept: str, many: bool = False) -> str:
   """!One concept's word in the game.
   @param doc      battle Document
   @param concept  e.g. "party"
   @param many     the plural
   @return the word
   """
   t = terms(doc).get(concept)
   if t is None:
      raise DocumentError(f"unknown concept {concept!r} (concepts: {', '.join(default_terms())})")
   return t["many" if many else "one"]


def kind_label(doc: Document, kind: str, many: bool = False) -> str:
   """!The game's word for a kind of entry (editor labels and headers).
   @param doc   battle Document
   @param kind  one of KINDS
   @param many  the plural
   @return e.g. "Trainer" for "parties" when the game calls parties so
   """
   if kind not in KIND_CONCEPTS:
      raise DocumentError(f"unknown kind {kind!r} (kinds: {', '.join(KINDS)})")
   return term(doc, KIND_CONCEPTS[kind], many)


def set_term(doc: Document, concept: str, one: str | None, many: str | None = None) -> None:
   """!Sets the game's word for a concept (None: the engine's default again).
   The compiler checks the words (length); editors show its message.
   @param doc      battle Document
   @param concept  e.g. "party"
   @param one      the word, or None to use the default
   @param many     its plural, or None for the plural the compiler derives (derived_plural())
   @return None
   """
   if concept not in default_terms():
      raise DocumentError(f"unknown concept {concept!r} (concepts: {', '.join(default_terms())})")
   t = data_of(doc, "terms").get("terms")
   if not isinstance(t, dict):
      t = data_of(doc, "terms")["terms"] = {}
   if one is None:
      t.pop(concept, None)
   elif not isinstance(one, str) or not one.strip():
      raise DocumentError("a term can't be empty")
   else:
      t[concept] = one.strip() if many is None else {"one": one.strip(), "many": many.strip()}


# -- presenters ------------------------------------------------------------------------------------

def _motion_text(m: Any, kind: str) -> str:
   """!How a presenter enters or leaves, in words.
   @param m     the presenter's "enter" or "exit" object, or None
   @param kind  "enter" or "exit"
   @return e.g. "slide from side, 24 frames"
   """
   bc = engine.tool("battle_compiler")
   m = m if isinstance(m, dict) else {}
   style = m.get("style", bc.MOTIONS[0])
   if style == "none":
      return "at once"
   if style == "stay":
      return style
   frames = m.get("frames", bc.DEFAULT_MOTION_FRAMES)
   if style == "sequence":
      return f"sequence {m.get('sequence')}, {frames} frames"
   if style == "slide":
      edge = m.get("from", bc.EDGES[0])
      return f"slide {'from' if kind == 'enter' else 'to'} {edge}, {frames} frames"
   return f"{style}, {frames} frames"


def stand(doc: Document, format_name: str | None = None, side: int = FOE_SIDE) -> tuple[int, int]:
   """!Where a side's presenters stand in a format (its "stands", or the side's first position).
   @param doc          battle Document
   @param format_name  format, or None for the first
   @param side         side index
   @return (x, y)
   """
   formats = entries(doc, "formats")
   if not formats:
      raise DocumentError("there is no format")
   f = entry(doc, "formats", format_name) if format_name is not None else formats[0]
   sides = f.get("sides") or []
   if not 0 <= side < len(sides):
      raise DocumentError(f"format {f.get('name')} has no side {side}")
   stands = f.get("stands")
   if isinstance(stands, list) and side < len(stands):
      return tuple(stands[side])
   return tuple(f["layout"][sides[side][0]])


def presenter_text(doc: Document, text: str, party: str) -> str:
   """!A presenter text as the game shows it: `{party}` filled in, `{@concept}` terms expanded.
   @param doc    battle Document
   @param text   the text
   @param party  party name
   @return the text
   """
   te = engine.tool("text_encoder")
   try:
      text = te.expand_terms(text, "text", terms(doc))
   except te.TextError as e:
      raise DocumentError(str(e)) from None
   return text.replace("{party}", party)


def intro(doc: Document, party: str, format_name: str | None = None, side: int = FOE_SIDE) -> list[str]:
   """!What a party's intro shows, step by step, as the engine runs it: its
   presenters enter, each one with an intro speaks (or the party_challenge
   message when none does), the ones leaving after the intro go; the others
   leave right before the party's first send-out (except those that stay).
   @param doc          battle Document
   @param party        party name
   @param format_name  format (where the presenters stand), or None for the first
   @param side         side the party is on
   @return lines
   """
   t = entry(doc, "parties", party)
   x, y = stand(doc, format_name, side)
   shown = [entry(doc, "presenters", n) for n in t.get("presenters", [])]
   lines = [f"{party} (side {side}, presenters stand at {x}, {y})"]
   for pr in shown:
      dx, dy = pr.get("at", [0, 0])
      sprite = pr.get("sprite") or "no sprite: text only"
      lines.append(f"  {pr['name']} enters ({_motion_text(pr.get('enter'), 'enter')}) at {x + dx}, {y + dy}"
                   f" [{sprite}]")
   spoke = False
   for pr in shown:
      if pr.get("intro"):
         lines.append(f"  {pr['name']}: {presenter_text(doc, pr['intro'], party)}")
         spoke = True
   challenge = (data_of(doc, "messages").get("messages") or {}).get("party_challenge", "")
   if not spoke and challenge:
      lines.append(f"  {presenter_text(doc, challenge, party)}")
   later = []
   for pr in shown:
      ex = pr.get("exit") if isinstance(pr.get("exit"), dict) else {}
      how = _motion_text(ex, "exit")
      if ex.get("style") == "stay":
         later.append(f"  {pr['name']} stays")
      elif ex.get("when") == "after_intro":
         lines.append(f"  {pr['name']} leaves after the intro ({how})")
      else:
         later.append(f"  {pr['name']} leaves before the first send-out ({how})")
   return lines + later


# -- presenter motion (as capsule::battle::presenter_view plays it) ----------------------------------

## Cues presenter_track() plays: an entrance, an exit, a return (the entrance motion again).
TRACK_CUES = ("enter", "exit", "return")
def still_motions() -> tuple[str, ...]:
   """!The presenter motion styles that do not move (no frames, edge or sequence: the engine's STILL_MOTIONS,
   battlec/presenters.py, E13b).
   @return style names
   """
   return tuple(engine.tool("battle_compiler").STILL_MOTIONS)


## Screen width when the engine's header cannot be read (hal::video::kScreenWidth).
DEFAULT_SCREEN_WIDTH = 240
## Screen height when the engine's header cannot be read (hal::video::kScreenHeight).
DEFAULT_SCREEN_HEIGHT = 160
## Opaque blend weight when the engine's header cannot be read (hal::video::kBlendMax).
DEFAULT_BLEND_MAX = 16
## Halves of a size: a sprite's centre is half its size from its corner (presenter_view's kHalf).
HALF = 2


def screen_size() -> tuple[int, int]:
   """!The engine's screen size.
   @return (width, height) in pixels
   """
   video = "capsule/hal/video.h"
   return (engine.header_constant(video, "kScreenWidth", DEFAULT_SCREEN_WIDTH),
           engine.header_constant(video, "kScreenHeight", DEFAULT_SCREEN_HEIGHT))


def blend_max() -> int:
   """!The weight of a fully shown sprite (hal::video::kBlendMax); 0 is hidden.
   @return weight
   """
   return engine.header_constant("capsule/hal/video.h", "kBlendMax", DEFAULT_BLEND_MAX)


def _c_div(a: int, b: int) -> int:
   """!Integer division as C++ does it (rounds toward zero, unlike Python's //).
   @param a  dividend
   @param b  divisor (not 0)
   @return quotient
   """
   q = abs(a) // abs(b)
   return q if (a < 0) == (b < 0) else -q


def sprite_sizes(path: str | Path) -> dict[str, tuple[int, int]]:
   """!The sprites of the game a file belongs to, with the OBJ size each is
   drawn at (presenter pickers and presenter_track()).
   @param path  any file of the game (its battle.json, say)
   @return {"sprite:NAME": (width, height)}, {} outside a game or without an asset manifest
   """
   from . import codepage, manifest_io, project, sprites   # local: codepage imports this module in functions too

   found = codepage.find_project(path)
   if found is None:
      return {}
   try:
      assets = project.game_files(project.open_project(found)).get("assets")
      data = manifest_io.load(assets) if assets is not None and assets.is_file() else {}
   except (DocumentError, OSError, ValueError):
      return {}
   out = {}
   for a in data.get("assets", []) if isinstance(data, dict) else []:
      if isinstance(a, dict) and a.get("kind") == "sprite" and isinstance(a.get("key"), str):
         w, h = a.get("width"), a.get("height")
         if isinstance(w, int) and isinstance(h, int):
            out[a["key"]] = sprites.smallest_size(w, h)
   return out


def presenter_track(compiled: JsonDict, presenter: str, format_name: str | None = None, side: int = FOE_SIDE,
                    cue: str = "enter", size: tuple[int, int] = (0, 0)) -> list[tuple[int, int, int, int]]:
   """!How a presenter's sprite moves for one cue, frame by frame, exactly as
   the engine's presenter_view plays it: frame 0 is the state right after the
   cue begins, each later entry one frame() further, the last one the state
   when the cue is done. A slide moves linearly between the presenter's place
   (the format's stand of the side plus the presenter's offset is the sprite's
   centre) and just off one edge; a fade blends it in or out. A presenter
   without a sprite, a "none" or "stay" motion and a motion of 0 frames take
   no time. A sequence cue hides the sprite while the sequence plays (its
   length is the sequence's, not known here): the track shows it hidden for
   one frame, then the end state.
   @param compiled     BattleProject.compile() result
   @param presenter    presenter name
   @param format_name  format, or None for the first
   @param side         side the presenter's party is on
   @param cue          one of TRACK_CUES
   @param size         the sprite's OBJ size (width, height); see sprite_sizes()
   @return [(frame, x, y, alpha)]: the sprite's top-left corner, and its blend weight from 0 (hidden) to blend_max()
   @throws DocumentError for an unknown presenter, format, side or cue
   """
   bc = engine.tool("battle_compiler")
   if cue not in TRACK_CUES:
      raise DocumentError(f"cue: one of {', '.join(TRACK_CUES)}")
   names = compiled["names"]
   if presenter not in names["presenters"]:
      raise DocumentError(f"no presenter {presenter!r}")
   pd = compiled["presenters"][names["presenters"].index(presenter)]
   if format_name is not None and format_name not in names["formats"]:
      raise DocumentError(f"no format {format_name!r}")
   fd = compiled["formats"][names["formats"].index(format_name) if format_name is not None else 0]
   if not 0 <= side < fd["sides"]:
      raise DocumentError(f"the format has sides 0 to {fd['sides'] - 1}")
   screen_w, screen_h = screen_size()
   shown = blend_max()
   has_sprite = pd["sprite"] != 0
   w, h = size if has_sprite else (0, 0)

   # Where it stands: the sprite's centre on the stand plus the offset.
   x = fd["stand_x"][side] + pd["dx"] - _c_div(w, HALF)
   y = fd["stand_y"][side] + pd["dy"] - _c_div(h, HALF)
   leaving = cue == "exit"
   motion = pd["exit"] if leaving else pd["enter"]
   style = bc.MOTIONS[motion["style"]]
   frames = motion["frames"]
   end = (0, x, y, 0 if leaving or not has_sprite else shown)
   if not has_sprite or style in ("none", "stay") or frames == 0:
      # Done at once: shown (or gone); a presenter that stays is still there.
      return [(0, x, y, shown if has_sprite and (not leaving or style == "stay") else 0)]
   if style == "sequence":
      return [(0, x, y, 0), (1,) + end[1:]]
   track = []
   if style == "slide":
      edge = bc.EDGES[motion["from"]]
      if edge == "side":   # the edge on the stand's half of the screen
         edge = "left" if x + _c_div(w, HALF) < _c_div(screen_w, HALF) else "right"
      ox, oy = {"left": (-w, y), "right": (screen_w, y), "top": (x, -h), "bottom": (x, screen_h)}[edge]
      fx, fy, tx, ty = (x, y, ox, oy) if leaving else (ox, oy, x, y)
      for f in range(frames):
         track.append((f, fx + _c_div((tx - fx) * f, frames), fy + _c_div((ty - fy) * f, frames), shown))
   else:   # fade
      for f in range(frames):
         weight = _c_div(shown * f, frames)
         track.append((f, x, y, shown - weight if leaving else weight))
   return track + [(frames,) + end[1:]]


def stat_formulas(doc: Document) -> list[str]:
   """!The stat formulas of a ruleset (the formulas the battle's stats name).
   @param doc  ruleset Document
   @return names, in ruleset order
   """
   given = doc.data.get("stat_formulas")
   return list(given) if isinstance(given, dict) else []


def named_formulas(doc: Document) -> list[str]:
   """!The named formulas of a ruleset: the formulas that declare "args" (pipelines call them like functions).
   @param doc  ruleset Document
   @return names, in ruleset order
   """
   given = doc.data.get("formulas")
   return [n for n, f in given.items() if isinstance(f, dict) and "args" in f] if isinstance(given, dict) else []


def formula_entry(doc: Document, slot: str) -> JsonDict:
   """!A ruleset formula as the ruleset writes it.
   @param doc   ruleset Document
   @param slot  formula slot, named formula or stat formula name
   @return {"expr", "range"} (a named formula also has "args"), or {} when the ruleset has none (live; change
           it only inside doc.edit())
   """
   section = "stat_formulas" if slot in stat_formulas(doc) else "formulas"
   f = (doc.data.get(section) or {}).get(slot)
   return f if isinstance(f, dict) else {}


def set_formula(doc: Document, slot: str, expr: str | None = None, lo: int | None = None,
                hi: int | None = None, args: list[str] | None = None) -> None:
   """!Changes a ruleset formula's expression, output range and/or arguments, or adds a formula. A stat
   formula stays one; an engine slot (exp_gain, reward, escape_odds) takes no arguments; any other name is a
   named formula (new ones start with no arguments).
   @param doc   ruleset Document
   @param slot  formula slot, named formula or stat formula name
   @param expr  new expression, or None to keep it
   @param lo    new lowest output, or None
   @param hi    new highest output, or None
   @param args  a named formula's argument names (each needs a range in the ruleset's "inputs"; an identifier,
                E13a: a dotted species.NAME is a derived expression's own input), or None to keep them
   @return None
   """
   slots = engine.tool("ruleset_compiler").FORMULA_SLOTS
   for a in args or []:
      problem = expressions.input_name_error(a)
      if problem is not None:
         raise DocumentError(f"{slot}: {problem}")
   stat = slot in stat_formulas(doc)
   if args is not None and (stat or slot in slots):
      raise DocumentError(f"{slot}: only a named formula takes arguments (its inputs are the engine's)")
   if not stat and slot not in slots and not engine.tool("ruleset_compiler").STAT_FORMULA_NAME.fullmatch(slot):
      raise DocumentError(f"{slot!r}: a formula name is a lower-case identifier")
   section = "stat_formulas" if stat else "formulas"
   f = doc.data.setdefault(section, {}).setdefault(slot, {"expr": "0", "range": [0, 0]})
   if not stat and slot not in slots:
      f.setdefault("args", [])
   if args is not None:
      f["args"] = [str(a) for a in args]
   if expr is not None:
      f["expr"] = expr
   rng = list(f.get("range", [0, 0]))
   if lo is not None:
      rng[0] = int(lo)
   if hi is not None:
      rng[1] = int(hi)
   f["range"] = rng


def formula_users(doc: Document, name: str) -> list[str]:
   """!The pipeline steps and formulas whose expressions call a named formula.
   @param doc   ruleset Document
   @param name  named formula
   @return "where" strings ("pipeline damage step 5", "formula other")
   """
   call = re.compile(rf"\b{re.escape(name)}\s*\(")
   found = []
   for pipeline, steps in (doc.data.get("pipelines") or {}).items():
      for i, s in enumerate(steps if isinstance(steps, list) else []):
         text = " ".join(str(s.get(k, "")) for k in ("expr", "span")) if isinstance(s, dict) else ""
         if call.search(text):
            found.append(f"pipeline {pipeline} step {i}")
   for other, f in (doc.data.get("formulas") or {}).items():
      if other != name and isinstance(f, dict) and call.search(str(f.get("expr", ""))):
         found.append(f"formula {other}")
   # the resources name formulas too (D-25: a move resource's max, a regen amount, a move's cost)
   project = logic.project_of(doc)
   if project is not None:
      d = merged(project.battle)
      for r in d.get("resources", []) if isinstance(d.get("resources"), list) else []:
         for key in ("max", "regen"):
            if isinstance(r, dict) and r.get(key) == name:
               found.append(f"resource {r.get('name')} {key}")
      for m in d.get("moves", []) if isinstance(d.get("moves"), list) else []:
         cost = m.get("cost") if isinstance(m, dict) else None
         for res, amount in (cost.items() if isinstance(cost, dict) else []):
            if amount == name:
               found.append(f"move {m.get('name')} cost {res}")
      # G4: the structure's training names its gain formula
      training = d.get("training")
      if isinstance(training, dict) and training.get("gain") == name:
         found.append("training gain")
   return found


def remove_formula(doc: Document, name: str) -> None:
   """!Removes a named formula nothing calls (the engine's slots stay; a stat formula goes with its stats).
   @param doc   ruleset Document
   @param name  named formula
   @return None
   """
   if name not in named_formulas(doc):
      raise DocumentError(f"no named formula {name!r} (named formulas: {', '.join(named_formulas(doc)) or 'none'})")
   users = formula_users(doc, name)
   if users:
      raise DocumentError(f"formula {name!r} is still called by: {', '.join(users[:REFERENCES_SHOWN])}")
   del doc.data["formulas"][name]
