"""!The effect logic of battle data (D-23 §1.6, §3.3, §3.4): the `.ceffect`
sources a battle manifest lists under "effects" (BattleProject.effects, one
SourceDocument each), read and written through the engine's effect compiler
(tools/effect_compiler.py: parse, format, the AST, the hook catalog and the
checks; the language is never re-implemented here).

    move "Snarl" {                       an owner: KIND "NAME" { members }
       hit {                             a handler: a move phase, `on HOOK [per_foe]`,
          stage target atk -1;           `point POINT` (pure) or `sub NAME`, with an
          yield;                         optional `when EXPR` and a block of statements
       }
    }

What it offers:
- owners: list (by kind), find ("kind:name" or a unique name), AST get/set,
  text get/set, add, remove and rename. Changing an owner rewrites only that
  owner's block in its file; comments and the rest of the file stay byte for
  byte. An AST is written in the compiler's canonical form.
- handlers of an owner, and the catalogs a handler picks from: the engine's
  hooks (effect_compiler.HOOKS: who may hold them, the context bindings, the
  value, the verdicts, the engine's draws, whether a handler may yield) and
  the ruleset's points.
- diagnostics with file, line and column (syntax errors, the compiler's
  checks and warnings with the battle's names, logic of unknown entries).
- AST operations for the block editor: insert, move and delete a statement,
  set an expression (by a path of keys and indices into an owner AST), and
  parse a statement or an expression from text.
- reference walks: the names effect code uses (stats and stages, statuses,
  volatiles, flags, types, categories, moves, items, passives, species,
  roles, points, texts, cues, tags, messages), found through the AST, so the
  studio's renames and removals follow them (core.battle, core.structure,
  core.pipelines). Manifest point handlers ({"point", "code"}) are walked
  too.

Edits of several files: a rename in the battle manifest also rewrites the
sources that name the entry. Every manifest Document of a BattleProject opens
an edit group (core.document.group()) for its edit() blocks (attach()), so
the source edits made inside one are part of its undo step: undoing (or
redoing) it from any of those Documents undoes (or redoes) them all, except a
source changed after it. The edits here that touch several files (add_owner()
listing a new source) make one group of their own; undoing that step also
drops the new source from the project. Parses are cached by each source's
revision; the compile behind diagnostics() and budgets() by every Document's
revision. Nothing here depends on a user interface.
"""
from __future__ import annotations

import copy
import json
import weakref
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from . import document, engine
from .document import Document, DocumentError

if TYPE_CHECKING:
   from .battle import BattleProject, SourceDocument

## A parsed JSON object (an AST node, a manifest entry).
JsonDict = dict[str, Any]
## A path into an AST: keys and list indices, from the owner node down.
AstPath = Sequence["str | int"]

## Schema of an owner or file AST (the engine's effect_compiler.SCHEMA_AST).
AST_SCHEMA = "capsule.effect-ast/1"
## Folder a battle's first source of a kind goes to when it has none (relative to the battle manifest).
DEFAULT_FOLDER = "effects"
## File name ending of an effect source.
SOURCE_SUFFIX = ".ceffect"
## Stem of the source new global rules go to when none holds one yet (F1: effects/field.ceffect).
GLOBAL_SOURCE = "field"
## Separates an owner kind from its name in an owner reference ("move:Strike").
OWNER_SEPARATOR = ":"
## What comes between an owner and the line in a "where" string ("effects/moves.ceffect: move Snarl line 174").
LINE_LABEL = " line "
## Label suffix of the source edits that follow a manifest edit.
FOLLOW_LABEL = " (logic)"
## Condition record lists of the battle manifest (E5) that effect code names (vol_on, side_on, field_on, has).
CONDITION_LISTS = ("volatiles", "side_conditions", "field_conditions")
## Structure list of the resources (D-25: battler and move pools by name).
RESOURCES_LIST = "resources"
## B1: structure list of the combination methods.
COMBINE_LIST = "combine_methods"
## B1: the name list of the combination methods' slot roles (`input.ROLE`).
COMBINE_SLOTS_LIST = "combine_slots"
## Palette template slot of the move resources (statement_templates()).
MOVE_RESOURCES_SLOT = "move_resources"
## Primitive arguments that are expressions of a known kind (the kind their names resolve in).
EXPECTED_ARGS = {("set_item", "item"): "item", ("set_passive", "passive"): "passive", ("use_move", "move"): "move",
                 ("set_types", "types"): "type"}
## Functions whose value is one of their arguments (an expected kind passes through).
PASS_THROUGH_CALLS = {"min", "max", "clamp", "pick"}
## Help of the effect language's functions (function_catalog(); the effect compiler's FUNCTIONS give the argument
## counts): (argument names, the optional ones last, what it gives).
FUNCTION_HELP = {
   "min": (("a", "b"), "the smaller of a and b"),
   "max": (("a", "b"), "the larger of a and b"),
   "clamp": (("v", "lo", "hi"), "v kept within [lo, hi]"),
   "abs": (("v",), "v without its sign"),
   "pick": (("i", "a", "b", "..."), "the i-th of the values after it (from 0)"),
   "scale": (("v", "q8"), "v times q8 / 256"),
   "chance": (("n", "m"), "true n times in m (draws a random number unless certain)"),
   "between": (("lo", "hi"), "a random number from lo to hi"),
   "rand": (("n",), "a random number from 0 to n - 1"),
   "is_foe": (("a", "b"), "whether battler b is a foe of battler a"),
   "is_ally": (("a", "b"), "whether battler b is an ally of battler a"),
   "odds": (("n", "m", "by", "on"), "true n times in m as the ruleset's effect_odds pipeline scales them, by "
                                    "battler `by` on battler `on` (default user on target; the pipeline reads "
                                    "the odds stat of both); without the pipeline: the plain odds, as chance()"),
}
## The function whose extra arguments are battlers (E9).
ODDS_FUNCTION = "odds"
## A function's argument shown for a variable count beyond the help's names ("pick(i, a, b, ...)").
MORE_ARGS = "..."
## Ref arguments naming volatiles through their counter / word slot.
SLOT_ARGS = {"counters", "words"}
## name_lists() key of the volatiles that have a counter slot.
COUNTER_LIST = "counters"
## name_lists() key of the volatiles that have a word slot.
WORD_LIST = "words"
## Ref arguments that are not names.
NOT_NAME_ARGS = {"index"}
## The has(...) form that looks a name up in several lists.
HAS_ANY = "?"
## Statements whose name declares a local, by the field holding it.
LOCAL_FIELDS = {"let": "name", "for": "var", "ask": "into"}
## Handler member keys and what they name in the handler list.
MEMBER_KEYS = ("on", "phase", "point", "sub")
## Tokens of an owner's head after its kind word: the name (a string), then the opening brace.
OWNER_NAME = 1
## See OWNER_NAME.
OWNER_BRACE = 2
## Operands of a comparison (left, right).
COMPARISON_OPERANDS = 2
## Steps of a handler's path in an owner AST ("handlers", INDEX).
HANDLER_PATH = 2
## Bounds of an analysed range (lo, hi).
RANGE_BOUNDS = 2
## Diagnostic code of logic for an entry the manifest does not have.
UNKNOWN_OWNER = "unknown-owner"
## Diagnostic code of an owner with logic in two places.
DUPLICATE_OWNER = "duplicate-owner"
## Diagnostic code of a source that does not parse.
SYNTAX = "syntax"


class Diagnostic(NamedTuple):
   """!One problem of the effect logic: where it is and what it says."""

   ## Source path as the manifest lists it ("" when the problem has no file).
   file: str
   ## 1-based line (0: none).
   line: int
   ## 1-based column (0: none).
   col: int
   ## "error" or "warning".
   severity: str
   ## Stable code (effect_compiler.MESSAGES keys, or this module's UNKNOWN_OWNER / DUPLICATE_OWNER / SYNTAX).
   code: str
   ## The text.
   message: str

   def text(self) -> str:
      """!The diagnostic as "file:line:col: severity: message".
      @return the text
      """
      d = self   # through another name: Doxygen 1.12 takes members read here for undocumented ones
      where = d.file or "logic"
      if d.line:
         where += f":{d.line}:{d.col}"
      return f"{where}: {d.severity}: {d.message}"


class OwnerRow(NamedTuple):
   """!One owner of the battle's logic (owners())."""

   ## Owner kind ("move", "passive", ...).
   kind: str
   ## The entry's name.
   name: str
   ## Source path as the manifest lists it.
   file: str
   ## Line of the owner's first token.
   line: int
   ## Its handler members (comments not counted).
   handlers: int


class HandlerRow(NamedTuple):
   """!One handler member of an owner (handlers())."""

   ## Index in the owner's "handlers" list (comments included: an AST path index).
   index: int
   ## "on", "phase", "point" or "sub".
   member: str
   ## The hook, phase, point or sub name.
   name: str
   ## `on switch_in per_foe`.
   per_foe: bool
   ## The `when` condition as text ("" for none).
   when: str
   ## Statements in its block (comments included).
   statements: int


class Use(NamedTuple):
   """!One name a piece of effect code uses (the reference walks)."""

   ## The structure list the name is from ("stats", "types", ...), or None when it cannot be told.
   list: str | None
   ## The name.
   name: str
   ## Where it is: "effects/moves.ceffect: move Snarl line 174".
   where: str
   ## The dict or list holding it (the walk renames through it).
   holder: Any
   ## Its key or index in the holder.
   key: Any


class _Span(NamedTuple):
   """!Where an owner block is in a source's text."""

   ## Owner kind.
   kind: str
   ## Owner name.
   name: str
   ## Offset of its first character.
   start: int
   ## Offset just past its closing brace.
   end: int
   ## Its first line.
   line: int


class _Parsed(NamedTuple):
   """!One source, parsed."""

   ## Path as the manifest lists it.
   rel: str
   ## The source's Document.
   doc: Any
   ## Its text.
   text: str
   ## The file AST.
   ast: JsonDict
   ## Node positions: id(node) -> (line, col).
   positions: dict[int, tuple[int, int]]
   ## (owner node, span) in file order (comments left out).
   owners: list[tuple[JsonDict, _Span]]


def _ec() -> Any:
   """!The engine's effect compiler module.
   @return module
   """
   return engine.tool("effect_compiler")


def _bc() -> Any:
   """!The engine's battle compiler module.
   @return module
   """
   return engine.tool("battle_compiler")


def point_owner_lists() -> dict[str, str]:
   """!The battle manifest lists whose entries may hold point handlers, with their owner kinds (the engine's
   OWNER_KINDS, battle_compiler's re-export: passives, items, statuses, weathers; E13b: moves, volatiles, side
   conditions).
   @return {manifest list: owner kind}
   """
   return dict(_bc().OWNER_KINDS)


def kind_lists() -> dict[str, str]:
   """!Owner kinds with the battle manifest list naming them (the engine's LOGIC_KINDS, battle_compiler's re-export;
   the global kind, F1: a game's own encounter rules, names no manifest entry and is not here: global_kind()).
   @return {owner kind: manifest list}
   """
   return dict(_bc().LOGIC_KINDS)


def global_kind() -> str:
   """!The owner kind of a game's own rules (F1, the engine's GLOBAL_KIND: `global "NAME" { on encounter {...} }`,
   any name, the encounter hooks only (GLOBAL_HOOKS); no manifest entry).
   @return the kind
   """
   return str(_bc().GLOBAL_KIND)


def battler_subjects() -> list[str]:
   """!The battler subjects effect logic names (holder, other, user, target: the engine's BATTLER_SUBJECTS).
   @return names
   """
   return list(_bc().BATTLER_SUBJECTS)


# -- grouped undo (manifest edits that also change sources) ------------------------------------------------------------

## BattleProject of each manifest Document: Document -> weak reference to the project.
_PROJECTS: weakref.WeakKeyDictionary[Document, Any] = weakref.WeakKeyDictionary()


def attach(project: BattleProject) -> None:
   """!Links a project's manifest Documents (battle, ruleset, structure) to its sources: reference walks on the
   battle Document find the sources, and each manifest edit() opens an edit group (core.document.group()), so
   the source edits made inside it are part of its undo step.
   @param project  the BattleProject
   @return None
   """
   for doc in (project.battle, project.ruleset, project.structure):
      if doc is None:
         continue
      _PROJECTS[doc] = weakref.ref(project)
      doc.group_edits = True


def manifest_view(doc: Document) -> JsonDict:
   """!The battle data's two manifests as one dict (core.battle.merged(): the content's and the structure's keys,
   sections live).
   @param doc  a manifest Document of the battle (or one on its own)
   @return dict
   """
   from . import battle as battle_core   # local: core.battle imports this module
   return battle_core.merged(doc)


def project_of(doc: Document | None) -> BattleProject | None:
   """!The BattleProject a manifest Document belongs to.
   @param doc  battle, ruleset or structure Document
   @return the project, or None (a Document opened on its own)
   """
   if doc is None:
      return None
   ref = _PROJECTS.get(doc)
   return ref() if ref is not None else None


def _write_source(source: SourceDocument, text: str, label: str) -> None:
   """!Replaces a source's text as one undo step (part of the edit group open now, if any).
   @param source  SourceDocument
   @param text    new text
   @param label   undo label
   @return None
   """
   if text == source.text:
      return
   with source.edit(label):
      source.data["text"] = text


def set_source_text(project: BattleProject, rel: str, text: str, label: str = "Edit logic text") -> None:
   """!Replaces a whole source's text as written (the text view's commit; it need not parse: diagnostics()
   reports the syntax error and the owner functions refuse the source until it parses again).
   @param project  BattleProject
   @param rel      path as the manifest lists it
   @param text     the new text
   @param label    undo label
   @return None
   """
   _write_source(project.effect_source(rel), text, label)


def _sync_sources(project: BattleProject, known: dict[str, SourceDocument]) -> None:
   """!Makes project.effects follow the battle manifest's list again after an undo or redo changed it: a source
   the list no longer names is dropped (and remembered in @p known), one it names again comes back.
   @param project  BattleProject
   @param known    every SourceDocument the step dealt with, by path
   @return None
   """
   from . import battle as battle_core   # local: core.battle imports this module
   listed = project.battle.data.get(battle_core.EFFECTS_KEY)
   listed = [rel for rel in listed if isinstance(rel, str)] if isinstance(listed, list) else []
   current = project.effects
   known.update(current)
   project.effects = {rel: current.get(rel, known.get(rel)) for rel in listed if rel in current or rel in known}


# -- sources ----------------------------------------------------------------------------------------------------------

def source_paths(project: BattleProject) -> list[str]:
   """!The effect sources, as the battle manifest lists them.
   @param project  BattleProject
   @return paths relative to the battle manifest
   """
   return list(project.effects)


def _line_starts(text: str) -> list[int]:
   """!Offset of each line's first character.
   @param text  source text
   @return offsets (line 1 first)
   """
   out = [0]
   for i, c in enumerate(text):
      if c == "\n":
         out.append(i + 1)
   return out


def _spans(text: str, rel: str) -> list[_Span]:
   """!Where each owner block is: from its kind word to its closing brace (the text parses).
   @param text  source text
   @param rel   its path (errors)
   @return spans in file order
   """
   ec = _ec()
   toks = ec.tokenize(text, rel)
   starts = _line_starts(text)

   def offset(t: Any) -> int:
      """!A token's offset.
      @param t  token
      @return offset
      """
      return starts[t.line - 1] + t.col - 1

   def is_sym(t: Any, s: str) -> bool:
      """!Whether a token is a symbol.
      @param t  token
      @param s  the symbol
      @return True when it is
      """
      return t.kind == "sym" and t.text == s

   out = []
   i = 0
   depth = 0
   while i < len(toks):
      t = toks[i]
      if is_sym(t, "{"):
         depth += 1
      elif is_sym(t, "}"):
         depth -= 1
      elif depth == 0 and t.kind == "name" and t.text in ec.OWNER_KINDS and i + OWNER_BRACE < len(toks) and \
            toks[i + OWNER_NAME].kind == "string" and is_sym(toks[i + OWNER_BRACE], "{"):
         j = i + OWNER_BRACE
         inner = 0
         # The matching closing brace (strings and comments are tokens of their own: their braces do not count).
         while j < len(toks):
            if is_sym(toks[j], "{"):
               inner += 1
            elif is_sym(toks[j], "}"):
               inner -= 1
               if inner == 0:
                  break
            j += 1
         out.append(_Span(t.text, toks[i + OWNER_NAME].text, offset(t), offset(toks[j]) + 1, t.line))
         i = j + 1
         continue
      i += 1
   return out


class _Cached(NamedTuple):
   """!One source's parse in the cache."""

   ## The source's revision when it was parsed.
   revision: int
   ## Its path.
   rel: str
   ## Its text.
   text: str
   ## The _Parsed, or the DocumentError of its syntax error.
   result: Any


## Parse cache: SourceDocument -> _Cached.
_PARSED: weakref.WeakKeyDictionary[Any, _Cached] = weakref.WeakKeyDictionary()


def _parse_shared(rel: str, doc: Any) -> _Parsed:
   """!One source, parsed, from the cache while the source's revision is unchanged (the result is shared:
   read it, never change it; _parse() gives a copy to change).
   @param rel  its path as the manifest lists it
   @param doc  its SourceDocument
   @return the parsed source
   @throws DocumentError on a syntax error (file, line and column in the message)
   """
   text = doc.text
   hit = _PARSED.get(doc)
   if hit is not None and (hit.revision, hit.rel, hit.text) == (doc.revision, rel, text):
      result = hit.result
   else:
      ec = _ec()
      try:
         ast, positions = ec.parse_positions(text, rel)
         nodes = [o for o in ast["owners"] if "owner" in o]
         result = _Parsed(rel, doc, text, ast, positions, list(zip(nodes, _spans(text, rel))))
      except ec.EffectError as e:
         result = DocumentError(str(e))
      _PARSED[doc] = _Cached(doc.revision, rel, text, result)
   if isinstance(result, DocumentError):
      raise DocumentError(str(result))
   return result


def _copy_parsed(p: _Parsed) -> _Parsed:
   """!A parsed source with its own AST (positions follow the copied nodes).
   @param p  parsed source
   @return the copy
   """
   memo: dict[int, Any] = {}
   ast = copy.deepcopy(p.ast, memo)
   positions = {id(memo[k]): pos for k, pos in p.positions.items() if k in memo}
   nodes = [o for o in ast["owners"] if "owner" in o]
   return _Parsed(p.rel, p.doc, p.text, ast, positions, list(zip(nodes, [s for _n, s in p.owners])))


def _parse(rel: str, doc: Any) -> _Parsed:
   """!Parses one source (a copy callers may change).
   @param rel  its path as the manifest lists it
   @param doc  its SourceDocument
   @return the parsed source
   @throws DocumentError on a syntax error (file, line and column in the message)
   """
   return _copy_parsed(_parse_shared(rel, doc))


def _shared_sources(project: BattleProject) -> list[_Parsed]:
   """!Every source, parsed, shared with the cache (read only).
   @param project  BattleProject
   @return parsed sources in manifest order
   @throws DocumentError when one has a syntax error
   """
   return [_parse_shared(rel, doc) for rel, doc in project.effects.items()]


def parsed_sources(project: BattleProject) -> list[_Parsed]:
   """!Every source, parsed (a fresh AST each call: callers may change it; the parse itself is cached by the
   source's revision).
   @param project  BattleProject
   @return parsed sources in manifest order
   @throws DocumentError when one has a syntax error
   """
   return [_parse(rel, doc) for rel, doc in project.effects.items()]


def source_error(project: BattleProject, rel: str) -> Diagnostic | None:
   """!A source's syntax error.
   @param project  BattleProject
   @param rel      path as the manifest lists it
   @return the error (file, line, column), or None when it parses
   """
   ec = _ec()
   doc = project.effect_source(rel)
   try:
      _parse_shared(rel, doc)
   except DocumentError:
      try:
         ec.parse(doc.text, rel)
      except ec.EffectError as e:
         return Diagnostic(rel, e.line, e.col, "error", SYNTAX, e.message)
   return None


def _format_owner(node: JsonDict) -> str:
   """!An owner's canonical block (no newline after its closing brace).
   @param node  owner node
   @return text
   """
   return _ec().format({k: v for k, v in node.items() if k != "schema"}).rstrip("\n")


def _splice(text: str, spans: Sequence[_Span], changes: dict[int, str | None]) -> str:
   """!Replaces or removes owner blocks, leaving every other character as it was.
   @param text     source text
   @param spans    the owners' spans
   @param changes  owner index -> new block text, or None to remove the block
   @return the new text
   """
   for i in sorted(changes, reverse=True):
      span = spans[i]
      block = changes[i]
      if block is not None:
         text = text[:span.start] + block + text[span.end:]
         continue
      # Removal: the block's line(s) and the blank lines after it go; one blank line stays between neighbours.
      line_start = text.rfind("\n", 0, span.start) + 1
      head = text[:line_start] if not text[line_start:span.start].strip() else text[:span.start]
      tail = text[span.end:].lstrip(" \t")
      while tail.startswith("\n"):
         tail = tail[1:]
      if head.strip() and tail:
         head = head.rstrip("\n") + "\n\n"
      elif not tail:
         head = head.rstrip("\n") + "\n" if head.strip() else ""
      text = head + tail
   return text


# -- owners -----------------------------------------------------------------------------------------------------------

def owner_kinds() -> list[str]:
   """!Owner kinds a battle's sources may hold (the engine's battlec LOGIC_KINDS, then its GLOBAL_KIND).
   @return kinds
   """
   return list(_bc().LOGIC_KINDS) + [global_kind()]


def _check_kind(kind: str) -> None:
   """!Refuses an owner kind battles cannot hold.
   @param kind  owner kind
   @return None
   """
   kinds = owner_kinds()
   if kind not in kinds:
      raise DocumentError(f"unknown owner kind {kind!r} (a battle's logic has {', '.join(kinds)})")


def owners(project: BattleProject, kind: str | None = None) -> list[OwnerRow]:
   """!The owners of the logic, in file order.
   @param project  BattleProject
   @param kind     only this owner kind, or None for all
   @return rows
   @throws DocumentError when a source has a syntax error
   """
   if kind is not None:
      _check_kind(kind)
   out = []
   for p in _shared_sources(project):
      for node, span in p.owners:
         if kind is None or span.kind == kind:
            count = sum(1 for h in node.get("handlers", []) if h.get("stmt") != "comment")
            out.append(OwnerRow(span.kind, span.name, p.rel, span.line, count))
   return out


def split_owner(ref: str) -> tuple[str | None, str]:
   """!An owner reference's kind and name.
   @param ref  "kind:name" or a name
   @return (kind or None, name)
   """
   kind, sep, name = ref.partition(OWNER_SEPARATOR)
   if sep and kind in owner_kinds():
      return kind, name
   return None, ref


def _find(project: BattleProject, ref: str) -> tuple[_Parsed, int]:
   """!An owner by reference.
   @param project  BattleProject
   @param ref      "kind:name" or a unique name
   @return (its parsed source, its index among the source's owners)
   @throws DocumentError when there is none, or the name is not unique
   """
   kind, name = split_owner(ref)
   found = [(p, i) for p in _shared_sources(project) for i, (_node, span) in enumerate(p.owners)
            if span.name == name and (kind is None or span.kind == kind)]
   if not found:
      raise DocumentError(f"no logic for {ref!r} (add it with: effect add KIND NAME)")
   if len(found) > 1:
      kinds = ", ".join(f"{p.owners[i][1].kind}:{name} in {p.rel}" for p, i in found)
      raise DocumentError(f"{ref!r} is not unique ({kinds}); name it as kind:name")
   return found[0]


def owner_file(project: BattleProject, ref: str) -> str:
   """!The source an owner is in.
   @param project  BattleProject
   @param ref      "kind:name" or a unique name
   @return path as the manifest lists it
   """
   return _find(project, ref)[0].rel


def owner_ast(project: BattleProject, ref: str) -> JsonDict:
   """!An owner's AST (capsule.effect-ast/1, the schema included).
   @param project  BattleProject
   @param ref      "kind:name" or a unique name
   @return a copy (change it, then set_owner_ast())
   """
   p, i = _find(project, ref)
   return {"schema": AST_SCHEMA, **copy.deepcopy(p.owners[i][0])}


def owner_text(project: BattleProject, ref: str) -> str:
   """!An owner's block as it is written in its file.
   @param project  BattleProject
   @param ref      "kind:name" or a unique name
   @return the text, from its kind word to its closing brace
   """
   p, i = _find(project, ref)
   span = p.owners[i][1]
   return p.text[span.start:span.end]


def _parse_owner(text: str, what: str) -> JsonDict:
   """!Text that must be exactly one owner block.
   @param text  the text
   @param what  what it is (errors)
   @return the owner node
   @throws DocumentError otherwise
   """
   ec = _ec()
   try:
      ast = ec.parse(text, what)
   except ec.EffectError as e:
      raise DocumentError(str(e)) from None
   items = ast["owners"]
   if len(items) != 1 or "owner" not in items[0]:
      raise DocumentError(f"{what}: give exactly one owner block (no comments outside it)")
   return items[0]


def _check_ast(ast: JsonDict) -> JsonDict:
   """!An owner AST that formats and parses back to itself.
   @param ast  owner AST (schema optional)
   @return the owner node (without the schema)
   @throws DocumentError when it is not a valid owner AST
   """
   ec = _ec()
   try:
      node = ec.from_json(ast)
   except (ec.EffectError, ValueError, TypeError) as e:
      raise DocumentError(f"not an owner AST: {e}") from None
   node.pop("schema", None)
   if "owner" not in node:
      raise DocumentError("not an owner AST (it has no \"owner\")")
   try:
      text = _format_owner(node)
   except (KeyError, TypeError, AttributeError, IndexError) as e:
      raise DocumentError(f"the AST is malformed ({type(e).__name__}: {e})") from None
   again = _parse_owner(text + "\n", "the formatted owner")
   if again != node:
      raise DocumentError("the AST does not round-trip through the formatter (a node is malformed)")
   return node


def set_owner_ast(project: BattleProject, ref: str, ast: JsonDict, label: str = "Edit logic") -> None:
   """!Replaces an owner's logic by an AST (written in canonical form; only that block of its file changes).
   The owner keeps its kind; a name the manifest does not have is reported by diagnostics() (rename_owner()
   checks it at once).
   @param project  BattleProject
   @param ref      the owner now: "kind:name" or a unique name
   @param ast      the new owner AST
   @param label    undo label
   @return None
   """
   p, i = _find(project, ref)
   node = _check_ast(ast)
   span = p.owners[i][1]
   if node["owner"]["kind"] != span.kind:
      raise DocumentError(f"an owner keeps its kind ({span.kind})")
   _write_source(p.doc, _splice(p.text, [s for _n, s in p.owners], {i: _format_owner(node)}), label)


def set_owner_text(project: BattleProject, ref: str, text: str, label: str = "Edit logic") -> None:
   """!Replaces an owner's block by text, as written (one owner block of the same kind and name).
   @param project  BattleProject
   @param ref      "kind:name" or a unique name
   @param text     the new block
   @param label    undo label
   @return None
   """
   p, i = _find(project, ref)
   span = p.owners[i][1]
   node = _parse_owner(text, p.rel)
   if (node["owner"]["kind"], node["owner"]["name"]) != (span.kind, span.name):
      raise DocumentError(f"the text is the logic of {node['owner']['kind']} {node['owner']['name']!r}, "
                          f"not of {span.kind} {span.name!r}")
   _write_source(p.doc, _splice(p.text, [s for _n, s in p.owners], {i: text.strip("\n")}), label)


def _entry_names(project: BattleProject, kind: str) -> list[str]:
   """!The manifest's entries an owner kind can be (a global owner names none: the global owners there are).
   @param project  BattleProject
   @param kind     owner kind
   @return names
   """
   if kind == global_kind():
      return [r.name for r in owners(project, kind)]
   return [e.get("name") for e in manifest_view(project.battle).get(kind_lists()[kind], []) if isinstance(e, dict)]


def _default_source(project: BattleProject, kind: str) -> str | None:
   """!Where new logic of a kind goes: the source that holds that kind already, else the one named after the
   kind's list, else the first source.
   @param project  BattleProject
   @param kind     owner kind
   @return path, or None when the manifest lists no source
   """
   paths = source_paths(project)
   for p in _shared_sources(project):
      if any(span.kind == kind for _n, span in p.owners):
         return p.rel
   named = [rel for rel in paths if Path(rel).stem == kind_lists().get(kind, GLOBAL_SOURCE)]
   return (named or paths or [None])[0]


def add_owner(project: BattleProject, kind: str, name: str, file: str | None = None,
              label: str = "Add logic") -> str:
   """!Adds an empty logic block for a manifest entry (`kind "name" {}`, at the end of its source). With no
   source listed yet, effects/LIST.ceffect (LIST: the kind's manifest list) is listed in the battle manifest (in
   a battle edit) and created.
   @param project  BattleProject
   @param kind     owner kind (owner_kinds())
   @param name     the entry
   @param file     source path as the manifest lists it, or None for the default (see _default_source())
   @param label    undo label
   @return the source path
   """
   _check_kind(kind)
   if kind == global_kind():
      if not isinstance(name, str) or not name.strip():
         raise DocumentError("a global rule needs a name")
   elif name not in _entry_names(project, kind):
      raise DocumentError(f"no {kind} {name!r} in the battle manifest's {kind_lists()[kind]}")
   if any(r.kind == kind and r.name == name for r in owners(project)):
      raise DocumentError(f"{kind} {name!r} already has logic (in {owner_file(project, kind + ':' + name)})")
   rel = file if file is not None else _default_source(project, kind)
   # One undo step: the manifest's new source (if any) and the block.
   with document.group(label):
      if rel is None:
         rel = _new_source(project, f"{DEFAULT_FOLDER}/{kind_lists().get(kind, GLOBAL_SOURCE)}{SOURCE_SUFFIX}",
                           label)
      source = project.effect_source(rel)
      text = source.text
      block = _format_owner({"owner": {"kind": kind, "name": name}, "handlers": []})
      if text.strip():
         text = text.rstrip("\n") + "\n\n" + block + "\n"
      else:
         text = block + "\n"
      _write_source(source, text, label)
   return rel


def _new_source(project: BattleProject, rel: str, label: str) -> str:
   """!Lists a new, empty source in the battle manifest and opens it (written by the next save).
   @param project  BattleProject
   @param rel      path relative to the battle manifest
   @param label    undo label of the manifest edit
   @return rel
   """
   from . import battle as battle_core   # local: core.battle imports this module
   with project.battle.edit(label):
      listed = project.battle.data.get(battle_core.EFFECTS_KEY)
      if not isinstance(listed, list):
         listed = project.battle.data[battle_core.EFFECTS_KEY] = []
      listed.append(rel)
   source = battle_core.SourceDocument("", (project.battle.path.parent / rel).resolve())
   source.dirty = True
   project.effects[rel] = source
   # Undoing the step unlists the source: the project forgets it (redo brings the same Document back); a group
   # that fails after this point and is rolled back forgets it too (no unlisted source for the next save).
   g = document.current_group()
   if g is not None:
      known = {rel: source}
      g.on_undo(lambda: _sync_sources(project, known))
      g.on_redo(lambda: _sync_sources(project, known))
      g.on_rollback(lambda: _sync_sources(project, known))
   return rel


def remove_owner(project: BattleProject, ref: str, label: str = "Remove logic") -> None:
   """!Removes an owner's logic block (the entry stays; a damaging move then hits with the engine's default).
   Comments above the block stay.
   @param project  BattleProject
   @param ref      "kind:name" or a unique name
   @param label    undo label
   @return None
   """
   p, i = _find(project, ref)
   _write_source(p.doc, _splice(p.text, [s for _n, s in p.owners], {i: None}), label)


def rename_owner(project: BattleProject, ref: str, new: str, label: str = "Rename logic") -> None:
   """!Gives an owner's logic to another entry of its kind (renaming an entry itself follows its logic:
   core.battle.rename_entry()).
   @param project  BattleProject
   @param ref      "kind:name" or a unique name
   @param new      the other entry's name
   @param label    undo label
   @return None
   """
   p, i = _find(project, ref)
   span = p.owners[i][1]
   if new == span.name:
      return
   if span.kind != global_kind() and new not in _entry_names(project, span.kind):
      raise DocumentError(f"no {span.kind} {new!r} in the battle manifest's {kind_lists()[span.kind]}")
   if any(r.kind == span.kind and r.name == new for r in owners(project)):
      raise DocumentError(f"{span.kind} {new!r} already has logic")
   node = copy.deepcopy(p.owners[i][0])
   node["owner"]["name"] = new
   _write_source(p.doc, _splice(p.text, [s for _n, s in p.owners], {i: _format_owner(node)}), label)


def format_sources(project: BattleProject, write: bool = False, label: str = "Format logic") -> dict[str, str]:
   """!The canonical text of every source (effect_compiler.format()).
   @param project  BattleProject
   @param write    replace the sources whose text differs
   @param label    undo label
   @return {path: canonical text} of the sources whose text differs from it
   @throws DocumentError when a source has a syntax error
   """
   out = {}
   for p in _shared_sources(project):
      canonical = _ec().format(p.ast)
      if canonical != p.text:
         out[p.rel] = canonical
         if write:
            _write_source(p.doc, canonical, label)
   return out


def canonical_text(project: BattleProject, rel: str) -> str:
   """!One source's canonical text.
   @param project  BattleProject
   @param rel      path as the manifest lists it
   @return text
   """
   return _ec().format(_parse_shared(rel, project.effect_source(rel)).ast)


# -- handlers and catalogs --------------------------------------------------------------------------------------------

def handlers(project: BattleProject, ref: str) -> list[HandlerRow]:
   """!An owner's handler members (comments left out; their index is still the AST path index).
   @param project  BattleProject
   @param ref      "kind:name" or a unique name
   @return rows
   """
   ec = _ec()
   p, i = _find(project, ref)
   out = []
   for j, h in enumerate(p.owners[i][0].get("handlers", [])):
      member = next((k for k in MEMBER_KEYS if k in h), None)
      if member is None:
         continue
      when = ec.format_expr(h["when"]) if "when" in h else ""
      out.append(HandlerRow(j, member, h[member], bool(h.get(ec.PER_FOE_WORD)), when, len(h.get("body", []))))
   return out


def member_names(project: BattleProject) -> dict[tuple[str, str], list[str]]:
   """!The hook, phase, point and sub names of every owner's handler members (the "uses hook" filter).
   @param project  BattleProject
   @return {(kind, name): [member names, in order]}
   @throws DocumentError when a source has a syntax error
   """
   out: dict[tuple[str, str], list[str]] = {}
   for p in _shared_sources(project):
      for node, span in p.owners:
         names = out.setdefault((span.kind, span.name), [])
         for h in node.get("handlers", []):
            member = next((k for k in MEMBER_KEYS if k in h), None)
            if member is not None:
               names.append(h[member])
   return out


def handler_text(handler: JsonDict) -> str:
   """!A handler member's head as the source writes it ("on switch_in per_foe when holder.alive").
   @param handler  handler node
   @return text (a comment: "# TEXT")
   """
   return _head_line(handler, lambda f: f.handler(handler, 0))


def statement_text(statement: JsonDict) -> str:
   """!A statement's first line as the source writes it, without its block ("if holder.alive",
   "inflict other Paralysis quiet").
   @param statement  statement node
   @return text
   """
   return _head_line(statement, lambda f: f.statement(statement, 0))


def _head_line(node: JsonDict, write: Callable[[Any], None]) -> str:
   """!The first line the formatter writes for a node, without a trailing "{", "{}" or ";".
   @param node   the node
   @param write  writes it into a Formatter
   @return text
   """
   ec = _ec()
   f = ec.Formatter()
   try:
      write(f)
   except (ec.EffectError, KeyError, TypeError, AttributeError, IndexError):
      return f"? {node.get('stmt', 'member')}"
   line = f.lines[0].strip() if f.lines else ""
   for tail in (" {}", " {", ";"):
      if line.endswith(tail):
         return line[:-len(tail)]
   return line


def hook_catalog(kind: str | None = None) -> list[JsonDict]:
   """!The engine's hooks and move phases (effect_compiler.HOOKS) a battle's owners may hold, for the handler
   picker.
   @param kind  only the hooks this owner kind may hold, or None for all
   @return [{"name", "owners" (kinds, sorted), "binds" (the context bindings), "value" ([lo, hi] or None: no
           value, modify not allowed), "results" (verdicts allowed), "draws" (the engine's draws around it),
           "yields" (a handler may yield or ask), "phase" (a move phase), "per_foe" (takes per_foe)}]
   """
   ec = _ec()
   bc = _bc()
   kinds = set(owner_kinds())
   if kind is not None:
      _check_kind(kind)
   out = []
   for h in ec.HOOKS:
      holders = sorted(set(h["owners"]) & kinds)
      # F1: a battle dispatches only the encounter hooks to global owners (the engine's GLOBAL_HOOKS)
      if h["name"] not in bc.GLOBAL_HOOKS:
         holders = [k for k in holders if k != global_kind()]
      if not holders or (kind is not None and kind not in holders):
         continue
      # Condition residual hooks may suspend in the language, not yet in this engine (battlec NO_SUSPEND_HOOKS).
      suspends = h["name"] in ec.YIELD_HOOKS and h["name"] not in bc.NO_SUSPEND_HOOKS
      yields = h["name"] in ec.YIELD_PHASES or suspends
      out.append({"name": h["name"], "owners": holders, "binds": h["binds"],
                  "value": list(h["value"]) if h["value"] is not None else None,
                  "results": sorted(h["results"]), "draws": h["draws"], "yields": yields,
                  "phase": h["name"] in ec.MOVE_PHASES,
                  # C5: try_switch takes the mark too (a foe's trap); an older engine only switch_in
                  "per_foe": h["name"] in getattr(ec, "PER_FOE_HOOKS", (ec.PER_FOE_HOOK,))})
   return out


def point_catalog(project: BattleProject) -> list[JsonDict]:
   """!The ruleset's points a handler can modify (`point NAME`; pure code: no draws, no yields).
   @param project  BattleProject
   @return [{"name", "id", "holder", "sources", "range"}] in id order
   """
   from . import pipelines   # local: core.pipelines imports this module
   out = []
   for i, name in enumerate(pipelines.point_names(project.ruleset)):
      pt = pipelines.point_entry(project.ruleset, name)
      out.append({"name": name, "id": i, "holder": pt.get("holder", pipelines.DEFAULT_HOLDER),
                  "sources": list(pt.get("sources") or []), "range": list(pt.get("range") or [])})
   return out


# -- names the logic may use -------------------------------------------------------------------------------------------

def _names(data: JsonDict, key: str) -> list[str]:
   """!The names of a manifest list of entries.
   @param data  manifest data
   @param key   list key
   @return names
   """
   given = data.get(key)
   return [e.get("name") for e in given if isinstance(e, dict) and isinstance(e.get("name"), str)] \
      if isinstance(given, list) else []


def _flag_names(data: JsonDict) -> list[str]:
   """!The manifest's move flags (battlec conditions.compile_move_flags(): none when it has no "move_flags").
   @param data  manifest data
   @return names
   """
   given = data.get("move_flags")
   return [f for f in given if isinstance(f, str)] if isinstance(given, list) else []


def _stage_names(data: JsonDict) -> list[str]:
   """!The stage names in index order (the manifest's "stages"; a stat's stage is named after the stat by default).
   @param data  battle manifest data
   @return names
   """
   from .structure import stages   # local: core.structure.stages imports core.battle, which imports this module
   return stages.names_of(data)


def _condition_entries(data: JsonDict) -> dict[str, list[JsonDict]]:
   """!The effect catalog's condition lists, read from the manifest as it is now (the battle compiler takes them
   from its compiled records: battlec conditions.condition_entries()). The effect checks need the names, which
   volatiles have a counter or a word slot (conditions.compile_volatiles() gives a counter to a volatile with
   "counter", a [min, max] duration or a chain, and a word to one with "word"), the own texts each condition
   names and the default turns. Text ids here only number the names (the checks look the names up).
   @param data  battle manifest data
   @return {"statuses", "weathers", "volatiles", "side_conditions", "field_conditions"} entry lists
   """
   bc = _bc()
   next_id = 0

   def texts_of(entry: JsonDict, slots: Sequence[str] | None) -> dict[str, int]:
      """!The own text slots an entry has, numbered in order (slots: the ones its kind may have, None: any)."""
      nonlocal next_id
      given = entry.get("texts")
      out = {}
      for slot, value in (given.items() if isinstance(given, dict) else ()):
         if value is not None and (slots is None or slot in slots):
            out[slot] = next_id
            next_id += 1
      return out

   def entries(key: str) -> list[JsonDict]:
      """!A list's entries that have a name."""
      given = data.get(key)
      return [e for e in given if isinstance(e, dict) and isinstance(e.get("name"), str)] \
         if isinstance(given, list) else []

   def turns(entry: JsonDict) -> int:
      """!An entry's default turns (0: none or not a number)."""
      value = entry.get("turns", 0)
      return value if isinstance(value, int) else 0

   return {
      "statuses": [{"name": e["name"], "texts": texts_of(e, bc.STATUS_TEXTS)} for e in entries("statuses")],
      "weathers": [{"name": e["name"], "texts": texts_of(e, bc.WEATHER_TEXTS), "turns": turns(e)}
                   for e in entries("weathers")],
      "volatiles": [{"name": v["name"],
                     "counter": bool(v.get("counter")) or isinstance(v.get("duration"), list) or "chain" in v,
                     "word": bool(v.get("word")), "texts": texts_of(v, None)} for v in entries("volatiles")],
      "side_conditions": [{"name": c["name"], "turns": turns(c), "texts": texts_of(c, None)}
                          for c in entries("side_conditions")],
      "field_conditions": [{"name": c["name"], "turns": turns(c), "texts": texts_of(c, None)}
                           for c in entries("field_conditions")],
   }


def resource_entries(data: JsonDict) -> list[JsonDict]:
   """!The resources as the effect compiler's catalog lists them.
   @param data  the battle data (manifest_view())
   @return [{"name", "scope"}] in manifest order
   """
   given = data.get(RESOURCES_LIST)
   return [{"name": r["name"], "scope": r.get("scope")} for r in (given if isinstance(given, list) else [])
           if isinstance(r, dict) and isinstance(r.get("name"), str)]


def name_lists(project: BattleProject) -> dict[str, list[str]]:
   """!The names effect code may use, by the effect compiler's structure list (from the manifests as they are
   now, unsaved edits included: volatiles, side / field conditions and move flags are the manifest's records).
   @param project  BattleProject
   @return {list key: names}
   """
   bc = _bc()
   d = manifest_view(project.battle)
   lists = {key: _names(d, key) for key in ("types", "categories", "statuses", "weathers", "moves", "items",
                                            "passives", "species")}
   # D-25: the resources by name (restore / raise, `holder.resource(NAME)`; catalog() adds their scopes)
   lists[RESOURCES_LIST] = _names(d, RESOURCES_LIST)
   stats = [st for st in d.get("stats", []) if isinstance(st, dict) and isinstance(st.get("name"), str)]
   lists["stats"] = [st["name"] for st in stats]
   lists["stages"] = _stage_names(d)
   for key in CONDITION_LISTS:
      lists[key] = _names(d, key)
   # The volatiles with a counter / word slot (what `holder.counter(X)` / `holder.word(X)` may name).
   vols = _condition_entries(d)["volatiles"]
   lists[COUNTER_LIST] = [v["name"] for v in vols if v["counter"]]
   lists[WORD_LIST] = [v["name"] for v in vols if v["word"]]
   lists["move_flags"] = _flag_names(d)
   texts = d.get("texts")
   lists["texts"] = list(texts) if isinstance(texts, dict) else []
   for key in ("tags", "cues"):
      lists[key] = [x for x in d.get(key, []) if isinstance(x, str)] if isinstance(d.get(key), list) else []
   # the engine messages the data gives (C1: an optional one it leaves out cannot be named)
   lists["messages"] = [m for m in _declared_messages(d) if m is not None]
   points = project.ruleset.data.get("points")
   lists["points"] = list(points) if isinstance(points, dict) else []
   from .structure import record   # local: core.structure.record imports core.battle, which imports this module
   lists["roles"] = record.role_names(project.battle)
   # E13a / E13b: the species' data columns (`holder.species_field(NAME)`; the ref picker lists them)
   fields = d.get("species_fields")
   lists["species_fields"] = [f["name"] for f in fields if isinstance(f, dict) and isinstance(f.get("name"), str)] \
      if isinstance(fields, list) else []
   # G1: the structure's delayed hits (`delay_hit WHO TURNS NAME`) and the AI profiles (bench scenarios' party "ai")
   lists["delayed_hits"] = _names(d, "delayed_hits")
   lists["ai_profiles"] = _names(d, "ai_profiles")
   # F1: the structure's timed field effects (`field_effect start NAME N`, `field.effect_active(NAME)`)
   lists["field_effects"] = _names(d, "field_effects")
   # F3: the structure's step effects (`field.step_effect == NAME` in an `on steps` handler)
   lists["step_effects"] = _names(d, "step_effects")
   # B1: the combination methods (`field.combine_method == NAME` in an `on combine` handler) and their slot roles
   # (`input.ROLE`; catalog() gives each role's input index)
   lists[COMBINE_LIST] = _names(d, COMBINE_LIST)
   lists[COMBINE_SLOTS_LIST] = list(_combine_slots(d))
   # G4: the species' form names, "base" first (effect `form WHO NAME`; the engine's form_names_of())
   species = d.get("species")
   lists["forms"] = list(bc.form_names_of([s for s in species if isinstance(s, dict)]
                                          if isinstance(species, list) else []))
   return lists


def _combine_slots(d: JsonDict) -> dict[str, int | None]:
   """!The combination methods' slot roles and their input indices (the engine's combine_slot_roles(): None when two
   methods give one role different indices).
   @param d  the manifests as one (manifest_view())
   @return role -> index or None
   """
   from .structure import combination   # local: see name_lists()
   given = d.get(COMBINE_LIST)
   methods = [m for m in given if isinstance(m, dict)] if isinstance(given, list) else []
   return _bc().combine_slot_roles([{"roles": combination.roles_of(m)} for m in methods])


def _declared_messages(d: JsonDict) -> list[str | None]:
   """!The engine message keys the battle data gives, at their Msg index (the engine's declared_messages(): None
   for an optional message it leaves out).
   @param d  the manifests as one (manifest_view())
   @return keys or None
   """
   msgs = d.get("messages")
   return list(_bc().declared_messages(msgs if isinstance(msgs, dict) else {}))


def catalog(project: BattleProject) -> Any:
   """!The battle's names as the effect compiler's Catalog, the way the battle compiler builds it (battlec
   logic.battle_catalog): role IDs from the layout, points in the ruleset's order with their value range.
   @param project  BattleProject
   @return effect_compiler.Catalog
   """
   from .structure import record   # local: see name_lists()
   bc = _bc()
   lists = name_lists(project)
   compiled, _error = record.compile_record(project.battle)
   layout = {"ids": compiled["ids"] if compiled is not None else {}}
   points = {name: {"id": i} for i, name in enumerate(lists["points"])}
   staged = lists["stages"]
   # the catalog wants each resource's scope (a move resource's `move.base(NAME)`, raise)
   # ... and the messages at their Msg ids (an optional one left out: the compiler's ABSENT_MESSAGE, never a name)
   view = manifest_view(project.battle)
   lists = {**lists, RESOURCES_LIST: resource_entries(view), "messages": _declared_messages(view),
            # B1: each slot role with its input index
            COMBINE_SLOTS_LIST: [{"name": r, "input": k} for r, k in _combine_slots(view).items()]}
   return bc.battle_catalog(lists, staged, layout, points, lists["texts"], lists["cues"], lists["tags"],
                            _condition_entries(manifest_view(project.battle)), lists["move_flags"])


# -- diagnostics ------------------------------------------------------------------------------------------------------

class _Checked(NamedTuple):
   """!One compile of every source (diagnostics(), budgets())."""

   ## Parsed sources (their own copies: the compiler's nodes), or [] when one has a syntax error.
   units: list[_Parsed]
   ## The effect compiler after run(), or None when a source has a syntax error.
   compiler: Any
   ## The diagnostics, in file order.
   diagnostics: list[Diagnostic]


## Compile cache: BattleProject -> (every Document's (id, revision), _Checked).
_CHECKED: weakref.WeakKeyDictionary[Any, tuple[tuple[tuple[int, int], ...], _Checked]] = \
   weakref.WeakKeyDictionary()


def _check(project: BattleProject) -> _Checked:
   """!Compiles every source as one unit, cached until a Document of the project changes.
   @param project  BattleProject
   @return the result
   """
   key = tuple((id(d), d.revision) for d in project.documents())
   hit = _CHECKED.get(project)
   if hit is not None and hit[0] == key:
      return hit[1]
   result = _compile_all(project)
   _CHECKED[project] = (key, result)
   return result


def _compile_all(project: BattleProject) -> _Checked:
   """!The compile behind _check().
   @param project  BattleProject
   @return the result
   """
   out: list[Diagnostic] = []
   units = []
   for rel in project.effects:
      error = source_error(project, rel)
      if error is not None:
         out.append(error)
      else:
         units.append(_parse(rel, project.effects[rel]))
   if out:
      return _Checked([], None, out)

   # One compile of every owner: each file's lines are moved past the lines of the files before it, so a
   # diagnostic's line tells its file.
   ec = _ec()
   positions: dict[int, tuple[int, int]] = {}
   offsets: list[tuple[int, str]] = []
   nodes = []
   seen: dict[tuple[str, str], str] = {}
   first = 0
   for p in units:
      offsets.append((first, p.rel))
      for node_id, (line, col) in p.positions.items():
         positions[node_id] = (line + first, col)
      for node, span in p.owners:
         key = (span.kind, span.name)
         if key in seen:
            out.append(Diagnostic(p.rel, span.line, 1, "error", DUPLICATE_OWNER,
                                  f"{span.kind} {span.name!r} has logic twice (also in {seen[key]})"))
         seen[key] = p.rel
         if span.kind != global_kind() and span.name not in _entry_names(project, span.kind):
            out.append(Diagnostic(p.rel, span.line, 1, "error", UNKNOWN_OWNER,
                                  f"logic of an unknown {span.kind} {span.name!r} (not in the battle manifest's "
                                  f"{kind_lists()[span.kind]})"))
         nodes.append(node)
      first += len(_line_starts(p.text))
   compiler = ec.Compiler({"schema": AST_SCHEMA, "owners": nodes}, catalog(project), "", positions).run()
   for d in compiler.diagnostics:
      file, line = "", d.line
      for start, rel in offsets:
         if d.line > start:
            file, line = rel, d.line - start
      out.append(Diagnostic(file, line, d.col, d.severity, d.code, d.message))
   order = {rel: i for i, rel in enumerate(project.effects)}
   return _Checked(units, compiler, sorted(out, key=lambda d: (order.get(d.file, len(order)), d.line, d.col)))


def diagnostics(project: BattleProject) -> list[Diagnostic]:
   """!The logic's problems: syntax errors, the effect compiler's checks and warnings with the battle's names,
   logic of entries the manifest does not have, an owner with logic twice. Every source compiles as one unit
   (hook budgets add up across files); each diagnostic names its file, line and column. Cached until a
   Document of the project changes.
   @param project  BattleProject
   @return diagnostics, errors and warnings, in file order
   """
   return list(_check(project).diagnostics)


class Budget(NamedTuple):
   """!What one handler costs, as the effect compiler's check measured it (budgets())."""

   ## Index in the owner's "handlers" list (as HandlerRow.index).
   index: int
   ## Deepest VM stack with its subs (0 for a point handler: pure code has no program).
   stack: int
   ## The VM's stack (effect_compiler.EFFECT_STACK).
   stack_limit: int
   ## Worst-case events of one run (one step for a handler that may yield).
   events: int
   ## Its limit: HOOK_EVENT_BUDGET, or EVENTS_PER_STEP for a handler that may yield.
   events_limit: int
   ## Whether it may draw random numbers (chance, between, rand) itself or in a sub.
   draws: bool
   ## Whether it may yield.
   yields: bool
   ## Whether it may ask (switch target, learn move, choice).
   asks: bool
   ## Locals in use with its subs.
   locals: int
   ## The VM's locals (EFFECT_LOCALS).
   locals_limit: int


def budgets(project: BattleProject, ref: str) -> list[Budget] | None:
   """!The budget of each handler member of an owner, read from the effect compiler's check of every source
   (Program.max_stack, events, flags: the compiler measures them while linking).
   @param project  BattleProject
   @param ref      "kind:name" or a unique name
   @return one Budget per handler member that compiled to a program or a point (in member order), or None when
           the logic has errors (the compiler measures only error-free logic)
   """
   ec = _ec()
   checked = _check(project)
   if checked.compiler is None or checked.compiler.errors():
      return None
   p, i = _find(project, ref)
   unit = next((u for u in checked.units if u.rel == p.rel), None)
   if unit is None or i >= len(unit.owners):
      return None
   node = unit.owners[i][0]
   programs = {id(prog.node): prog for prog in checked.compiler.program_list()}
   out = []
   for j, h in enumerate(node.get("handlers", [])):
      if "point" in h:   # pure: no program, no events, no draws
         out.append(Budget(j, 0, ec.EFFECT_STACK, 0, ec.HOOK_EVENT_BUDGET, False, False, False, 0, ec.EFFECT_LOCALS))
         continue
      prog = programs.get(id(h))
      if prog is None:
         continue
      limit = ec.EVENTS_PER_STEP if prog.yields else ec.HOOK_EVENT_BUDGET
      out.append(Budget(j, prog.max_stack, ec.EFFECT_STACK, prog.events, limit, bool(prog.flags & ec.PROGRAM_RNG),
                        bool(prog.flags & ec.PROGRAM_YIELDS), bool(prog.flags & ec.PROGRAM_ASKS), prog.locals,
                        ec.EFFECT_LOCALS))
   return out


def expression_range(project: BattleProject, ref: str, path: AstPath, expression: Any = None) -> tuple[int, int] | None:
   """!The analysed range of an expression in an owner's handler (the effect compiler's range_of() with the
   handler's hook or point as context).
   @param project     BattleProject
   @param ref         "kind:name" or a unique name
   @param path        path of the expression slot in the owner AST (it starts "handlers", INDEX)
   @param expression  the expression (node or text) to analyse in that slot, or None for the one there
   @return (lo, hi), or None when the compiler cannot tell (a local assigned since its let, an unknown read,
           a bad path)
   """
   ec = _ec()
   ast = owner_ast(project, ref)
   if len(path) <= HANDLER_PATH or path[0] != "handlers":
      return None
   try:
      handler = node_at(ast, path[:HANDLER_PATH])
      e = node_at(ast, path) if expression is None else \
         parse_expression(expression) if isinstance(expression, str) else expression
   except DocumentError:
      return None
   compiler = ec.Compiler({"schema": AST_SCHEMA, "owners": []}, catalog(project))
   if "point" in handler:
      compiler.context = {"point": True, "hook": handler["point"]}
   else:
      hook = handler.get("on", handler.get("phase"))
      spec = ec.HOOKS[ec.HOOK[hook]] if hook in ec.HOOK else None
      compiler.context = {"spec": spec, "hook": hook}
   try:
      # The locals declared before the expression's statement, with the ranges the compiler gives them.
      _declare_before(compiler, handler.get("body", []), tuple(path[:HANDLER_PATH]) + ("body",), tuple(path[:-1]))
      r = compiler.range_of(e)
   except (ec.EffectError, KeyError, TypeError, ValueError, IndexError):
      return None
   return (int(r[0]), int(r[1])) if isinstance(r, (tuple, list)) and len(r) == RANGE_BOUNDS else None


def _declare_before(compiler: Any, body: list[Any], at: tuple[Any, ...], stop: tuple[Any, ...]) -> bool:
   """!Declares, in the compiler's scope, the locals of the statements before a statement (in source order,
   nested blocks included): a let with its value's analysed range, a loop variable as a battler, an asked
   local and an assigned one with an unknown range (as the compiler's own let / assign do).
   @param compiler  effect_compiler.Compiler (context set)
   @param body      statements
   @param at        their block's path
   @param stop      path of the statement to stop at
   @return True when the walk reached @p stop
   """
   ec = _ec()
   for k, st in enumerate(body):
      here = at + (k,)
      if here == stop:
         return True
      if not isinstance(st, dict):
         continue
      stmt = st.get("stmt")
      if stmt == "let":
         compiler.declare(st["name"], st, compiler.static_kind(st["value"]) or "int", compiler.range_of(st["value"]))
      elif stmt == "for":
         compiler.declare(st["var"], st, "battler", (0, ec.MAX_BATTLERS - 1))
      elif stmt == "ask":
         compiler.declare(st["into"], st, "int", None)
      elif stmt == "assign" and "name" in st.get("target", {}):
         found = compiler.scope.find(st["target"]["name"])
         if found is not None:
            for b in reversed(compiler.scope.blocks):
               if st["target"]["name"] in b:
                  b[st["target"]["name"]] = (found[0], found[1], None)   # no longer the initializer's range
                  break
      for key in STATEMENT_BLOCKS.get(stmt, ()):
         if isinstance(st.get(key), list) and _declare_before(compiler, st[key], here + (key,), stop):
            return True
   return False


def function_catalog() -> list[tuple[str, int, int, str, str]]:
   """!The effect language's functions for the block editor's function picker: the effect compiler's FUNCTIONS
   (argument counts), with FUNCTION_HELP's argument names and help.
   @return [(name, least args, most args, signature e.g. "odds(n, m[, by, on])", help)] by name
   """
   out = []
   for name, (lo, hi) in sorted(_ec().FUNCTIONS.items()):
      names, text = FUNCTION_HELP.get(name, ((), ""))
      shown = [n for n in names if n != MORE_ARGS] or [f"a{i}" for i in range(lo)]
      optional = shown[lo:hi] + ([MORE_ARGS] if MORE_ARGS in names else [])
      rest = f"[, {', '.join(optional)}]" if optional else ""
      out.append((name, lo, hi, f"{name}({', '.join(shown[:lo])}{rest})", text))
   return out


def function_text(name: str, count: int, subjects: list[str] | None = None) -> str:
   """!A call to insert from the function picker: placeholder numbers for its values; odds()'s battlers from
   the effect compiler's ODDS_DEFAULT_SUBJECTS (or the given subjects).
   @param name      a function of the effect language
   @param count     its argument count (clamped to the function's range)
   @param subjects  battlers for odds()'s by / on, or None for the defaults
   @return e.g. "odds(1, 2, user, target)"
   @throws DocumentError for an unknown function
   """
   ec = _ec()
   if name not in ec.FUNCTIONS:
      raise DocumentError(f"unknown function {name!r} (functions: {', '.join(sorted(ec.FUNCTIONS))})")
   lo, hi = ec.FUNCTIONS[name]
   count = max(lo, min(hi, int(count)))
   args = ["1"] * count
   if name == ODDS_FUNCTION:
      shown = list(subjects or ec.ODDS_DEFAULT_SUBJECTS)
      for i in range(ec.ODDS_FIRST_BATTLER, count):
         args[i] = shown[(i - ec.ODDS_FIRST_BATTLER) % len(shown)]   # wraps for a single given subject
      args[1] = "2"   # odds(1, 2): once in two
   return f"{name}({', '.join(args)})"


def ref_catalog() -> dict[str, list[tuple[str, str | None, str]]]:
   """!The reads effect code has, by subject group (the block editor's ref picker): the effect compiler's
   BATTLER_REFS, MOVE_REFS, FIELD_REFS, SIDE_REFS and GLOBAL_REFS.
   @return {"battler" | "move" | "field" | "side" | "global": [(field, what its argument names or None, value
           kind)]}
   """
   ec = _ec()
   tables = {"battler": ec.BATTLER_REFS, "move": ec.MOVE_REFS, "field": ec.FIELD_REFS, "side": ec.SIDE_REFS,
             "global": ec.GLOBAL_REFS}
   return {group: [(name, spec.arg, spec.kind) for name, spec in table.items()] for group, table in tables.items()}


def words() -> dict[str, list[str]]:
   """!The language's words by class, for syntax colours and completion (from the effect compiler's tables).
   @return {"keywords": statement and member words, "primitives": statement primitives, "owners": owner kinds,
           "hooks": hooks and move phases, "functions": functions, "context": subjects and global reads,
           "modes": flag and mode words}
   """
   ec = _ec()
   # every flag word of the primitives' signatures ("flags:quiet,silent"; E13b's silent has no FLAG_BITS entry)
   flags = set()
   for sig in ec.PRIMITIVES.values():
      for _field, kind in sig:
         head, _colon, words = kind.partition(":")
         if head == FLAGS_KIND:
            flags |= set(words.split(","))
   modes = set(ec.MODIFY_MODES) | set(ec.SWITCH_MODES) | set(ec.FLAG_BITS) | set(ec.BATTLER_SETS) | \
      set(ec.ASK_KINDS) | flags | {ec.PER_FOE_WORD, "true", "false", "announce", "at", "about", "value", "heal"}
   # C5: `none`, the none value of the kind it is compared with (`user.targeted_by == none`)
   context = set(ec.CONTEXT_WORDS) | ({ec.NONE_WORD} if hasattr(ec, "NONE_WORD") else set())
   return {"keywords": sorted(ec.STATEMENT_WORDS | {"else"}), "primitives": sorted(ec.PRIMITIVES),
           "owners": sorted(ec.OWNER_KINDS), "hooks": [h["name"] for h in ec.HOOKS],
           "functions": sorted(ec.FUNCTIONS), "context": sorted(context), "modes": sorted(modes)}


# -- AST operations (the block editor) --------------------------------------------------------------------------------

def parse_expression(text: str) -> Any:
   """!An expression from text, as an AST node.
   @param text  e.g. "move.type == Flame and holder.alive"
   @return the node (an int for a bare number)
   @throws DocumentError when the text is not exactly one expression
   """
   ec = _ec()
   try:
      p = ec.EffectParser(text, "expression")
      node = p.expr()
      if p.peek().kind != "eof":
         raise p.error(f"unexpected {p.peek().text!r} after the expression")
   except ec.EffectError as e:
      raise DocumentError(str(e)) from None
   return ec.from_json({"owner": {}, "value": node})["value"]


def parse_statement(text: str) -> JsonDict:
   """!One statement from text, as an AST node.
   @param text  e.g. "inflict other Paralysis quiet;"
   @return the node
   @throws DocumentError when the text is not exactly one statement
   """
   ec = _ec()
   try:
      p = ec.EffectParser(text, "statement")
      node = p.statement()
      if p.peek().kind != "eof":
         raise p.error(f"unexpected {p.peek().text!r} after the statement")
   except ec.EffectError as e:
      raise DocumentError(str(e)) from None
   return ec.from_json({"owner": {}, "value": node})["value"]


def format_id(name: str) -> str:
   """!A name in a primitive's or a read's argument position, as source (quoted only when it must be).
   @param name  the name
   @return text
   """
   return _ec().format_id(name)


def format_expression(e: Any) -> str:
   """!An expression node as source text.
   @param e  expression node
   @return text
   """
   return _ec().format_expr(e)


def node_at(ast: JsonDict, path: AstPath) -> Any:
   """!The node a path leads to.
   @param ast   owner AST
   @param path  keys and indices
   @return the node
   @throws DocumentError when the path leads nowhere
   """
   node: Any = ast
   for step in path:
      try:
         node = node[step]
      except (KeyError, IndexError, TypeError):
         raise DocumentError(f"no node at {list(path)!r} (stopped at {step!r})") from None
   return node


def _statement_list(ast: JsonDict, path: AstPath) -> tuple[list[Any], int]:
   """!The block holding a statement, and the statement's index.
   @param ast   owner AST
   @param path  path of the statement (its last step is an index)
   @return (block list, index)
   """
   if not path or not isinstance(path[-1], int):
      raise DocumentError(f"{list(path)!r} is not a statement's path (it ends with its index in a block)")
   block = node_at(ast, path[:-1])
   if not isinstance(block, list) or not 0 <= path[-1] < len(block):
      raise DocumentError(f"no statement at {list(path)!r}")
   return block, path[-1]


def insert_statement(ast: JsonDict, block_path: AstPath, index: int | None, statement: JsonDict | str) -> int:
   """!Inserts a statement into a block (a handler's "body", an if's "then" / "else", a loop's "body", ...).
   @param ast         owner AST (changed)
   @param block_path  path of the block list
   @param index       position, or None for the end
   @param statement   statement node, or its text (parse_statement())
   @return its index
   """
   block = node_at(ast, block_path)
   if not isinstance(block, list):
      raise DocumentError(f"{list(block_path)!r} is not a block")
   node = parse_statement(statement) if isinstance(statement, str) else copy.deepcopy(statement)
   if not isinstance(node, dict) or "stmt" not in node:
      raise DocumentError("a statement node has \"stmt\"")
   at = len(block) if index is None else max(0, min(len(block), int(index)))
   block.insert(at, node)
   return at


def delete_statement(ast: JsonDict, path: AstPath) -> JsonDict:
   """!Deletes a statement.
   @param ast   owner AST (changed)
   @param path  path of the statement
   @return the statement taken out
   """
   block, i = _statement_list(ast, path)
   return block.pop(i)


def move_statement(ast: JsonDict, path: AstPath, delta: int) -> bool:
   """!Moves a statement up or down its block.
   @param ast    owner AST (changed)
   @param path   path of the statement
   @param delta  -1 up, +1 down
   @return True when it moved
   """
   block, i = _statement_list(ast, path)
   j = i + delta
   if not 0 <= j < len(block):
      return False
   block[i], block[j] = block[j], block[i]
   return True


def set_expression(ast: JsonDict, path: AstPath, expression: Any) -> None:
   """!Sets an expression slot: a handler's "when", an if's "cond", a let's "value", a primitive's argument, ...
   (a "when" may be set where there was none; None removes an optional slot).
   @param ast         owner AST (changed)
   @param path        path of the slot (its last step is the key)
   @param expression  AST node, its text (parse_expression()), or None to remove the slot
   @return None
   """
   if not path:
      raise DocumentError("an expression's path ends with its key")
   holder = node_at(ast, path[:-1])
   key = path[-1]
   if not isinstance(holder, (dict, list)):
      raise DocumentError(f"no node at {list(path[:-1])!r}")
   if expression is None:
      if not isinstance(holder, dict):
         raise DocumentError("only an optional key can be removed")
      holder.pop(key, None)
      return
   value = parse_expression(expression) if isinstance(expression, str) else copy.deepcopy(expression)
   if isinstance(holder, list):
      if not isinstance(key, int) or not 0 <= key < len(holder):
         raise DocumentError(f"no element {key!r} at {list(path[:-1])!r}")
   holder[key] = value


def move_statement_to(ast: JsonDict, path: AstPath, block_path: AstPath, index: int | None) -> list[Any]:
   """!Moves a statement to a position in any block of the owner (drag and drop in the block view).
   @param ast         owner AST (changed)
   @param path        path of the statement
   @param block_path  path of the block it goes to (as it is before the move)
   @param index       its position there (counted before the move), or None for the end
   @return the statement's new path
   @throws DocumentError for a block inside the statement itself, or a bad path
   """
   if list(block_path[:len(path)]) == list(path):
      raise DocumentError("a statement cannot go into its own blocks")
   source, i = _statement_list(ast, path)
   target = node_at(ast, block_path)
   if not isinstance(target, list):
      raise DocumentError(f"{list(block_path)!r} is not a block")
   at = len(target) if index is None else max(0, min(len(target), int(index)))
   if target is source and i < at:
      at -= 1   # the statement's own place goes first
   node = source.pop(i)
   target.insert(at, node)
   # The target block's path may have moved with the removal (it came after the statement in the same list).
   return _path_of(ast, node) or [*block_path, at]


def _path_of(ast: Any, wanted: Any, path: list[Any] | None = None) -> list[Any] | None:
   """!The path of a node (by identity).
   @param ast     where to look
   @param wanted  the node
   @param path    path of @p ast
   @return path, or None
   """
   path = path or []
   if ast is wanted:
      return path
   items = ast.items() if isinstance(ast, dict) else enumerate(ast) if isinstance(ast, list) else ()
   for key, value in items:
      if isinstance(value, (dict, list)):
         found = _path_of(value, wanted, [*path, key])
         if found is not None:
            return found
   return None


## Fields of the control statements the block form edits: (AST key, field kind) (see statement_fields()).
CONTROL_FIELDS = {
   "let": [("name", "name"), ("value", "expr")],
   "assign": [("target", "expr"), ("op", "choice:=,+=,-="), ("value", "expr")],
   "if": [("cond", "expr")],
   "chance": [("n", "expr"), ("m", "expr")],
   "repeat": [("count", "expr"), ("max", "int")],
   "for": [("var", "name"), ("set", "sets"), ("of", "subj")],
   "call": [("sub", "name")],
   "ask": [("kind", "asks"), ("who", "subj"), ("into", "name")],
}
## Blocks of a block statement, the main one first.
STATEMENT_BLOCKS = {"if": ("then", "else"), "chance": ("body", "else"), "repeat": ("body",), "for": ("body",)}
## Field kinds whose value is an expression.
EXPRESSION_KINDS = {"expr", "opt_expr", "kw"}
## The signature kind of an optional `WORD NAME` part ("kwid:WORD:LIST", effect_compiler PRIMITIVES; G1: use_move's
## `unless FLAG`); statement_fields() gives it as "kwid:LIST".
KWID_KIND = "kwid"


def statement_fields(statement: JsonDict) -> list[tuple[str, str]]:
   """!The fields of a statement the block form edits, from the effect compiler's signatures.
   @param statement  statement node
   @return [(AST key, kind)]; kinds: expr, opt_expr, kw (an optional expression), exprs (a comma list), subj,
           kws (an optional subject), side (a subject), name, int, id:LIST, opt_id:LIST, flag, mode:A,B,
           choice:A,B; for/ask: sets (a battler set), asks (a request kind)
   """
   ec = _ec()
   stmt = statement.get("stmt")
   if stmt in CONTROL_FIELDS:
      return list(CONTROL_FIELDS[stmt])
   out = []
   for field, kind in ec.PRIMITIVES.get(stmt, []):
      head, _, rest = kind.partition(":")
      if head == "flags":
         out += [(flag, "flag") for flag in rest.split(",")]
      elif head == "mode":
         _default, _colon, words = rest.partition(":")   # mode:DEFAULT:A,B
         out.append((field, "mode:" + words))
      elif head == "kws":
         out.append((field, "kws"))
      elif head == KWID_KIND:
         # G1: `WORD NAME`, optional (use_move ... unless FLAG): a name of the list after the keyword
         _word, _colon, list_key = rest.partition(":")
         out.append((field, f"{KWID_KIND}:{list_key}"))
      else:
         out.append((field, kind))
   return out


def field_choices(kind: str) -> list[str]:
   """!The words a choice field offers.
   @param kind  a statement_fields() kind
   @return words ([] for a free field)
   """
   ec = _ec()
   head, _, rest = kind.partition(":")
   if head in ("mode", "choice"):
      return rest.split(",")
   if head == "sets":
      return list(ec.BATTLER_SETS)
   if head == "asks":
      return list(ec.ASK_KINDS)
   return []


def field_text(statement: JsonDict, field: str, kind: str) -> str:
   """!A field's value as the form shows it.
   @param statement  statement node
   @param field      AST key
   @param kind       its statement_fields() kind
   @return text ("" when an optional field is not given; "1" / "" for a flag)
   """
   if field not in statement:
      return ""
   value = statement[field]
   if kind == "flag":
      return "1" if value else ""
   if kind in EXPRESSION_KINDS:
      return format_expression(value)
   if kind == "exprs":
      return ", ".join(format_expression(v) for v in value)
   return str(value)


def set_field(ast: JsonDict, path: AstPath, field: str, kind: str, text: str) -> None:
   """!Sets one field of a statement from the form's text (an empty optional field is removed).
   @param ast    owner AST (changed)
   @param path   path of the statement
   @param field  AST key
   @param kind   its statement_fields() kind
   @param text   the text ("1" / "" for a flag)
   @return None
   @throws DocumentError when the text is not a value of that kind
   """
   node = node_at(ast, path)
   if not isinstance(node, dict):
      raise DocumentError(f"no statement at {list(path)!r}")
   text = text.strip()
   optional = kind in ("opt_expr", "kw", "kws", "flag") or kind.startswith("opt_id:") or \
      kind.startswith(KWID_KIND + ":")
   if not text and optional:
      node.pop(field, None)
   elif not text:
      raise DocumentError(f"{field} needs a value")
   elif kind == "flag":
      node[field] = True
   elif kind in EXPRESSION_KINDS:
      node[field] = parse_expression(text)
   elif kind == "exprs":
      node[field] = [parse_expression(part) for part in text.split(",")]
   elif kind == "int":
      try:
         node[field] = int(text, 0)
      except ValueError:
         raise DocumentError(f"{field}: a whole number (got {text!r})") from None
   else:
      choices = field_choices(kind)
      if choices and text not in choices:
         raise DocumentError(f"{field}: one of {', '.join(choices)} (got {text!r})")
      node[field] = text


## Statement palette of the block view: group -> [(label, template text; "{LIST}" stands for the battle's first
## name in name_lists()[LIST], "{move_resources}" for its first move resource)]; statement_templates() fills them
## in, then adds a template for every other primitive of the effect compiler (PALETTE_MORE, S17).
PALETTE = {
   "Control": [("if", "if holder.alive {}"), ("if / else", "if holder.alive {} else {}"),
               ("chance", "chance 1/2 {}"), ("odds", "if odds(1, 2) {}"), ("repeat", "repeat 2 max 2 {}"),
               ("for each", "for each in foes(holder) {}")],
   "Values": [("let", "let n = 0;"), ("assign", "holder.counter({volatiles}) = 1;")],
   "Actions": [("damage", "damage;"), ("damage_hp", "damage_hp target 1;"), ("heal", "heal holder 1;"),
               ("inflict", "inflict target {statuses};"), ("cure", "cure holder;"),
               ("stage", "stage target {stages} -1;"), ("volatile on", "vol_on target {volatiles};"),
               ("volatile off", "vol_off target {volatiles};"), ("weather", "weather {weathers} 5;"),
               ("switch", "switch holder;"), ("lock", "lock user;"), ("unlock", "unlock user;"),
               ("use move", "use_move user {moves};"), ("consume item", "consume_item holder;"),
               ("set types", "set_types holder {types};"), ("restore", "restore holder {resources};"),
               ("raise", "raise holder {move_resources} 1;"),
               # E13b: no text per stage (one text for the whole change, e.g. a haze), every stage back to 0, a
               # pending hit at the target's position (the move's land phase after 2 ends of turn), the reward
               # pool, the battle's end
               ("stage (silent)", "stage target {stages} -1 silent;"), ("reset stages", "reset_stages target;"),
               ("delay", "delay target dealt 2;"), ("reward", "reward 1;"), ("end battle", "end_battle;"),
               # G1: a delayed hit (the land phase's `damage` works it out), a call that refuses a flagged move
               ("delay hit", "delay_hit target 2 {delayed_hits};"),
               ("use move unless", "use_move user user.targeted_by unless {move_flags};")],
   "Results": [("modify", "modify by 1.5;"), ("immune", "immune;"), ("block", "block;"), ("absorb", "absorb;"),
               ("stop", "stop;"),
               ("fail", "fail;"), ("return", "return;"), ("yield", "yield;"),
               ("ask", "ask switch_target holder into picked;")],
   "Presentation": [("text", "text {texts};"), ("say", "say {messages} at holder;"), ("announce", "announce;"),
                    ("cue", "cue {cues};")],
   # G4: a form change (battle-only in battle; kept on the record outside it), a transformation by the species'
   # rules (an item's use_field logic: trigger item_use), training values of a stat
   "Growth": [("form", "form holder {forms};"), ("transform", "transform holder;"),
              ("train", "train holder {stats} 1;")],
   # F1: a timed field effect (an item's use_field logic), the encounter hooks' changes (the lead's passive or
   # held item, a global rule: on encounter / on encounter_made)
   "Field": [("start field effect", "field_effect start {field_effects} 100;"),
             ("encounter rate", "encounter_rate 3 2;"), ("encounter levels", "encounter_levels 1 1;"),
             ("level bias", "encounter_level_bias 1;"), ("skip below", "encounter_skip_below holder.level;"),
             ("prefer type", "encounter_type {types} 1 2;"), ("reroll", "encounter_reroll;"),
             # F3: a step effect's run (on steps): which one runs, a member's resource going down (hit points out
             # of battle: the member is on no position, damage_hp needs one)
             ("step effect runs", "if field.step_effect == {step_effects} {}"),
             ("lose resource", "holder.resource({resources}) -= 1;")],
   # B1: a combination's run (on combine): which method runs, an input's values onto the result (copied, the better
   # of several picks, a chance, added), a refusal
   "Combination": [("method runs", "if field.combine_method == {combine_methods} {}"),
                   ("inherit", "inherit {roles} from input.1;"),
                   ("inherit pick", "inherit_pick {roles} 3;"),
                   ("inherit odds", "inherit_odds {roles} from input.1 1 2;"),
                   ("inherit add", "inherit_add {roles} 1;"),
                   ("refuse", "fail;")],
}


## The signature kind of a primitive's flag words ("flags:A,B", effect_compiler PRIMITIVES).
FLAGS_KIND = "flags"
## Palette group of the primitives PALETTE has no template for (generated from their signatures).
PALETTE_MORE = "More actions"
## Template words of the signature parts generated_template() writes (a subject, a side, a value).
TEMPLATE_SUBJECT = "holder"
## The side a generated template names.
TEMPLATE_SIDE = "side(holder)"
## The value a generated template gives an expression.
TEMPLATE_VALUE = "1"


def generated_template(name: str) -> str:
   """!A palette template for a primitive from its effect compiler signature (PRIMITIVES): a subject is the holder,
   a side the holder's, a name the list's first ("{LIST}"), a value 1; optional parts, flags and modes (their
   defaults) are left out.
   @param name  a primitive of the effect compiler
   @return template text (statement_templates() fills the "{LIST}" slots)
   """
   parts = []
   for _field, kind in _ec().PRIMITIVES[name]:
      head, _, rest = kind.partition(":")
      if head == "subj":
         parts.append(TEMPLATE_SUBJECT)
      elif head == "side":
         parts.append(TEMPLATE_SIDE)
      elif head == "id":
         parts.append("{" + rest + "}")
      elif head in ("expr", "exprs"):
         parts.append(TEMPLATE_VALUE)
   return " ".join([name] + parts) + ";"


def statement_templates(project: BattleProject) -> list[tuple[str, str, str | None]]:
   """!The block palette: statements to insert, with the battle's first name where one is needed (PALETTE, then a
   generated_template() for each primitive of the effect compiler PALETTE leaves out, in PALETTE_MORE).
   @param project  BattleProject
   @return [(group, label, statement text, or None when the battle has no name for it)]
   """
   lists = name_lists(project)
   # `raise` names a move resource (its raises role)
   lists[MOVE_RESOURCES_SLOT] = [r["name"] for r in resource_entries(manifest_view(project.battle))
                                 if r["scope"] == "move"]
   out = []
   palette = {group: list(entries) for group, entries in PALETTE.items()}
   # the statement word of each template ("stage target ...;" -> stage)
   covered = {template.split()[0].rstrip(";") for entries in PALETTE.values() for _label, template in entries}
   more = [(name.replace("_", " "), generated_template(name)) for name in _ec().PRIMITIVES if name not in covered]
   if more:
      palette[PALETTE_MORE] = more
   for group_name, entries in palette.items():
      for label, template in entries:
         text = template
         if text is not None:
            for key, names in lists.items():
               slot = "{" + key + "}"
               if slot in text:
                  text = text.replace(slot, format_id(names[0])) if names else None
                  if text is None:
                     break
         out.append((group_name, label, text))
   return out


# -- reference walks --------------------------------------------------------------------------------------------------

class _Walker:
   """!Collects the names one owner's code uses (Use rows), resolving each to the structure list it is from the
   way the effect compiler does: a primitive's or ref's argument names its list; a bare name in an expression
   is a local, or a name of the kind its context expects (the other side of a comparison, an argument of a
   known kind), or of the one value list that has it."""

   def __init__(self, lists: dict[str, list[str]], label: Callable[[Any], str]) -> None:
      """!Creates a walker.
      @param lists  name_lists()
      @param label  node -> "where" string
      """
      ec = _ec()
      ## Names by list.
      self.lists = lists
      ## Where a node is.
      self.label = label
      ## Uses found.
      self.uses = []
      ## Locals of the handler being walked.
      self.locals = set()
      ## The compiler's tables.
      self.ec = ec

   def add(self, list_key: str | None, name: Any, holder: Any, key: Any, node: Any) -> None:
      """!Records one use.
      @param list_key  the list, or None
      @param name      the name (non-strings are ignored)
      @param holder    dict or list holding it
      @param key       its key or index
      @param node      the nearest node with a position
      @return None
      """
      if isinstance(name, str):
         self.uses.append(Use(list_key, name, self.label(node), holder, key))

   def owner(self, node: JsonDict) -> None:
      """!Walks an owner: its header, tags and members.
      @param node  owner node
      @return None
      """
      kind = node["owner"]["kind"]
      self.add(kind_lists().get(kind), node["owner"]["name"], node["owner"], "name", node)
      for i, tag in enumerate(node.get("tags", [])):
         self.add("tags", tag, node["tags"], i, node)
      for h in node.get("handlers", []):
         if h.get("stmt") == "comment":
            continue
         self.locals = set()
         self.declare(h.get("body", []))
         if "point" in h:
            self.add("points", h["point"], h, "point", h)
         if "when" in h:
            self.expr(h["when"], h, None)
         self.block(h.get("body", []), h)

   def declare(self, body: Any) -> None:
      """!Collects the locals a block declares (let, for, ask ... into), nested blocks included.
      @param body  statement list (or any node)
      @return None
      """
      if isinstance(body, list):
         for s in body:
            self.declare(s)
      elif isinstance(body, dict):
         field = LOCAL_FIELDS.get(body.get("stmt"))
         if field is not None and isinstance(body.get(field), str):
            self.locals.add(body[field])
         for key in ("body", "then", "else"):
            if key in body:
               self.declare(body[key])

   def static_kind(self, e: Any) -> str | None:
      """!The kind of an expression's value when it is evident (a ref's kind; min / max / clamp / pick of it).
      @param e  expression
      @return kind, or None
      """
      if not isinstance(e, dict):
         return None
      if "ref" in e:
         spec = self.ref_spec(e)
         return spec.kind if spec is not None else None
      if e.get("call") in PASS_THROUGH_CALLS and e.get("args"):
         return self.static_kind(e["args"][0])
      return None

   def ref_spec(self, e: JsonDict) -> Any:
      """!The ref spec of a ref node (the compiler's ref tables).
      @param e  ref node
      @return RefSpec, or None for an unknown ref
      """
      ec = self.ec
      parts = str(e["ref"]).split(".")
      if len(parts) == 1:
         return ec.GLOBAL_REFS.get(parts[0])
      table = {"move": ec.MOVE_REFS, "field": ec.FIELD_REFS, "side": ec.SIDE_REFS}.get(parts[0], ec.BATTLER_REFS)
      return table.get(".".join(parts[1:]))

   def expr(self, e: Any, at: Any, expect: str | None) -> None:
      """!Walks an expression.
      @param e       expression
      @param at      the nearest node with a position
      @param expect  the kind its context expects, or None
      @return None
      """
      if not isinstance(e, dict):
         return
      where = e if self.label(e) else at
      if "name" in e:
         self.bare_name(e, where, expect)
      elif "ref" in e:
         self.ref(e, where)
      elif "op" in e:
         args = e.get("args", [])
         if e["op"] in self.ec.COMPARISONS and len(args) == COMPARISON_OPERANDS:
            left, right = args
            self.expr(left, where, self.static_kind(right))
            self.expr(right, where, self.static_kind(left))
         else:
            for a in args:
               self.expr(a, where, None)
      elif "call" in e:
         passes = e["call"] in PASS_THROUGH_CALLS
         for a in e.get("args", []):
            self.expr(a, where, expect if passes else None)

   def bare_name(self, e: JsonDict, at: Any, expect: str | None) -> None:
      """!A bare name: a local (not a use), a name of the expected kind, or of the one value list that has it.
      @param e       name node
      @param at      position node
      @param expect  expected kind, or None
      @return None
      """
      name = e["name"]
      if name in self.locals:
         return
      kinds = self.ec.VALUE_KINDS
      if expect in kinds:
         self.add(kinds[expect], name, e, "name", at)
         return
      having = [key for key in kinds.values() if name in self.lists.get(key, [])]
      self.add(having[0] if len(having) == 1 else None, name, e, "name", at)

   def ref(self, e: JsonDict, at: Any) -> None:
      """!A ref's argument, when it is a name.
      @param e   ref node
      @param at  position node
      @return None
      """
      spec = self.ref_spec(e)
      arg = e.get("arg")
      if spec is None or not isinstance(arg, str):
         return
      if spec.has == HAS_ANY:
         having = [key for _kind, key in self.ec.HAS_LOOKUP if arg in self.lists.get(key, [])]
         self.add(having[0] if having else None, arg, e, "arg", at)
      elif spec.arg in SLOT_ARGS:
         self.add("volatiles", arg, e, "arg", at)
      elif spec.arg is not None and spec.arg not in NOT_NAME_ARGS:
         self.add(spec.arg, arg, e, "arg", at)

   def block(self, body: Any, at: Any) -> None:
      """!Walks a statement list.
      @param body  statements
      @param at    position node of the block's head
      @return None
      """
      for s in body if isinstance(body, list) else []:
         if isinstance(s, dict):
            self.statement(s, s if self.label(s) else at)

   def statement(self, s: JsonDict, at: Any) -> None:
      """!Walks one statement.
      @param s   statement node
      @param at  its position node
      @return None
      """
      stmt = s.get("stmt")
      if stmt == "let":
         self.expr(s.get("value"), at, None)
      elif stmt == "assign":
         self.expr(s.get("target"), at, None)
         self.expr(s.get("value"), at, self.static_kind(s.get("target")))
      elif stmt == "if":
         self.expr(s.get("cond"), at, None)
         self.block(s.get("then"), at)
         self.block(s.get("else"), at)
      elif stmt == "chance":
         self.expr(s.get("n"), at, None)
         self.expr(s.get("m"), at, None)
         self.block(s.get("body"), at)
         self.block(s.get("else"), at)
      elif stmt == "repeat":
         self.expr(s.get("count"), at, None)
         self.block(s.get("body"), at)
      elif stmt == "for":
         self.block(s.get("body"), at)
      elif stmt in self.ec.PRIMITIVES:
         self.primitive(s, at)

   def primitive(self, s: JsonDict, at: Any) -> None:
      """!Walks a primitive's arguments by its signature (effect_compiler.PRIMITIVES).
      @param s   statement node
      @param at  its position node
      @return None
      """
      stmt = s["stmt"]
      for field, kind in self.ec.PRIMITIVES[stmt]:
         head, _, rest = kind.partition(":")
         if field not in s:
            continue
         if head in ("id", "opt_id"):
            self.add(rest, s[field], s, field, at)
         elif head == KWID_KIND:
            _keyword, _, list_key = rest.partition(":")
            self.add(list_key, s[field], s, field, at)   # G1: `unless FLAG` names a move flag
         elif head in ("expr", "opt_expr", "kw"):
            self.expr(s[field], at, EXPECTED_ARGS.get((stmt, field)))
         elif head == "exprs":
            for e in s[field] if isinstance(s[field], list) else []:
               self.expr(e, at, EXPECTED_ARGS.get((stmt, field)))


def _source_uses(project: BattleProject, parsed: Sequence[_Parsed] | None = None) -> list[tuple[_Parsed, int, Use]]:
   """!Every name every owner of the sources uses.
   @param project  BattleProject
   @param parsed   parsed sources (parsed_sources()), or None to parse them
   @return [(source, owner index, use)]
   """
   lists = name_lists(project)
   out = []
   for p in parsed if parsed is not None else _shared_sources(project):
      for i, (node, span) in enumerate(p.owners):

         def label(n: Any, p: _Parsed = p, span: _Span = span) -> str:
            """!Where a node is ("" when it has no position).
            @param n     node
            @param p     its source
            @param span  its owner
            @return the "where" string
            """
            pos = p.positions.get(id(n))
            return f"{p.rel}: {span.kind} {span.name}{LINE_LABEL}{pos[0]}" if pos else ""

         walker = _Walker(lists, label)
         walker.owner(node)
         out += [(p, i, u) for u in walker.uses]
   return out


def _code_owner(kind: str, name: str, handler: JsonDict) -> str:
   """!A manifest point handler as the battle compiler reads it: an owner around `point NAME CODE`.
   @param kind     owner kind
   @param name     the entry
   @param handler  {"point": name, "code": text}
   @return source text
   """
   return f"{kind} {json.dumps(name, ensure_ascii=False)} {{\n   point {handler['point']} {handler['code']}\n}}\n"


def _code_of(member: JsonDict) -> str:
   """!A point member as manifest handler code: the text after `point NAME` (canonical form).
   @param member  the point member node
   @return code text
   """
   ec = _ec()
   f = ec.Formatter()
   f.handler(member, 0)
   head = f"point {member['point']} "
   lines = list(f.lines)
   lines[0] = lines[0][len(head):] if lines[0].startswith(head) else lines[0]
   return "\n".join(lines)


def _manifest_uses(doc: Document, lists: dict[str, list[str]]) -> list[tuple[JsonDict, JsonDict, Use]]:
   """!The names manifest point handlers ({"point", "code"} in passives, items, statuses and weathers) use.
   @param doc    a manifest Document of the battle (both manifests: statuses and weathers are structure)
   @param lists  name_lists()
   @return [(the handler dict, its parsed member, use)] (handlers whose code does not parse are left out: the
           battle compiler reports them)
   """
   ec = _ec()
   out = []
   data = manifest_view(doc)
   for key, kind in point_owner_lists().items():
      for e in data.get(key, []):
         if not isinstance(e, dict) or not isinstance(e.get("name"), str):
            continue
         for h in e.get("handlers", []) if isinstance(e.get("handlers"), list) else []:
            if not (isinstance(h, dict) and isinstance(h.get("point"), str) and isinstance(h.get("code"), str)):
               continue
            try:
               member = ec.parse(_code_owner(kind, e["name"], h))["owners"][0]["handlers"][0]
            except (ec.EffectError, IndexError, KeyError):
               continue
            where = f"{kind} {e['name']} (point {h['point']} handler)"
            walker = _Walker(lists, lambda _n, where=where: where)
            header = {"kind": kind, "name": e["name"]}
            walker.owner({"owner": header, "handlers": [member]})
            # The owner around the code is the entry itself, not a use of its name.
            out += [(h, member, u) for u in walker.uses if u.holder is not header]
   return out


def name_uses(project: BattleProject) -> dict[str, dict[str, list[str]]]:
   """!Every name the logic uses, by list (usage counts and "used by" lists of the editors).
   @param project  BattleProject
   @return {list key: {name: ["where", ...]}} (names that cannot be told apart are under "")
   @throws DocumentError when a source has a syntax error
   """
   out: dict[str, dict[str, list[str]]] = {}
   for _p, _i, u in _source_uses(project):
      out.setdefault(u.list or "", {}).setdefault(u.name, []).append(u.where)
   for _h, _m, u in _manifest_uses(project.battle, name_lists(project)):
      out.setdefault(u.list or "", {}).setdefault(u.name, []).append(u.where)
   return out


def _manifest_rename(doc: Document, lists: Sequence[str], old: str, new: str | None,
                     names: dict[str, list[str]]) -> list[str]:
   """!Finds (and renames) a name in the manifest's point handler code.
   @param doc    battle Document (renames happen in the edit running on it)
   @param lists  the list keys the name is from
   @param old    the name
   @param new    new name, or None to only look
   @param names  name_lists() (or the same shape)
   @return "where" strings
   """
   found = []
   changed: dict[int, tuple[JsonDict, JsonDict]] = {}
   for h, member, u in _manifest_uses(doc, names):
      if u.list in lists and u.name == old:
         found.append(u.where)
         if new is not None:
            u.holder[u.key] = new
            changed[id(h)] = (h, member)
   for h, member in changed.values():
      if member.get("point") != h["point"]:   # the point itself was renamed
         h["point"] = member["point"]
      h["code"] = _code_of(member)
   return found


def _lists_from_doc(doc: Document) -> dict[str, list[str]]:
   """!name_lists() for a battle Document without a project (no ruleset points, no roles).
   @param doc  battle Document (a merged view: every key its own)
   @return {list key: names}
   """
   d = manifest_view(doc)
   lists = {key: _names(d, key) for key in ("types", "categories", "statuses", "weathers", "moves", "items",
                                            "passives", "species", RESOURCES_LIST)}
   stats = [st["name"] for st in d.get("stats", []) if isinstance(st, dict) and isinstance(st.get("name"), str)]
   lists.update({"stats": stats, "stages": _stage_names(d), "move_flags": _flag_names(d),
                 "points": [], "roles": []})
   for key in CONDITION_LISTS:
      lists[key] = _names(d, key)
   return lists


def references(doc: Document, lists: Sequence[str], name: str, new: str | None = None,
               label: str = "Rename") -> list[str]:
   """!Finds (and optionally renames) a name in the effect logic: the sources of the project the Document
   belongs to (attach()) and the manifest's point handler code. Renames rewrite only the owner blocks that
   change (canonical form); the source edits join the edit running on the manifest (one undo step), and so do
   the bench scenarios a rename rewrites (core.bench.follow_rename(); not in the result) [S14].
   @param doc    battle or ruleset Document (its project's sources are walked)
   @param lists  list keys the name is from (a stat: ("stats", "stages"); an entry: its list, e.g. ("moves",))
   @param name   the name
   @param new    new name, or None to only look
   @param label  undo label of the source edits (FOLLOW_LABEL added)
   @return "where" strings, one per use ("effects/moves.ceffect: move Snarl line 174")
   @throws DocumentError when a source does not parse (a rename could not follow it)
   """
   project = project_of(doc)
   names = name_lists(project) if project is not None else _lists_from_doc(doc)
   # The manifests' code changes only inside an edit of the battle or structure Document (they are partners: one
   # edit covers both), not through a ruleset edit.
   found = _manifest_rename(doc, lists, name, new, names) if project is None or doc is not project.ruleset else []
   if project is None:
      return found
   parsed = parsed_sources(project)
   changed: dict[str, set[int]] = {}
   for p, i, u in _source_uses(project, parsed):
      if u.list in lists and u.name == name:
         found.append(u.where)
         if new is not None:
            u.holder[u.key] = new
            changed.setdefault(p.rel, set()).add(i)
   for p in parsed:
      if p.rel in changed:
         spans = [s for _n, s in p.owners]
         text = _splice(p.text, spans, {i: _format_owner(p.owners[i][0]) for i in changed[p.rel]})
         _write_source(p.doc, text, label + FOLLOW_LABEL)
   if new is not None:   # the bench scenarios naming it follow in the same step (not counted: not logic)
      from . import bench   # local: core.bench imports the battle modules
      for key in lists:
         bench.follow_rename(project, key, name, new, label)
   return found


def per_owner(wheres: Sequence[str]) -> list[str]:
   """!"where" strings of references(), one per owner (an owner naming a name three times counts once).
   @param wheres  references() result
   @return the owners' "where" strings without their line ("effects/moves.ceffect: move Snarl"), in order
   """
   out = []
   for where in wheres:
      head = where.rsplit(LINE_LABEL, 1)[0]
      if head not in out:
         out.append(head)
   return out


def point_users(doc: Document) -> dict[tuple[str, str], list[str]]:
   """!The points each owner's handlers modify: the manifest's point handlers and the sources' point members
   (a source with a syntax error is left out).
   @param doc  battle Document
   @return {(manifest list, entry name): [point names, in order]}
   """
   out: dict[tuple[str, str], list[str]] = {}
   data = manifest_view(doc)
   lists = point_owner_lists()
   for key in lists:
      for e in data.get(key, []):
         if isinstance(e, dict) and isinstance(e.get("handlers"), list):
            pts = [h["point"] for h in e["handlers"] if isinstance(h, dict) and isinstance(h.get("point"), str)]
            if pts:
               out.setdefault((key, e.get("name")), []).extend(pts)
   project = project_of(doc)
   if project is None:
      return out
   for rel, source in project.effects.items():
      try:
         p = _parse_shared(rel, source)
      except DocumentError:
         continue   # a source being typed that does not parse yet: its points show again when it does
      for node, span in p.owners:
         key = kind_lists().get(span.kind)
         pts = [h["point"] for h in node.get("handlers", []) if "point" in h]
         if key in lists and pts:
            out.setdefault((key, span.name), []).extend(pts)
   return out
