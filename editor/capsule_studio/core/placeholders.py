"""!Field placeholders and terms of a scripts manifest (D-22 decision 6,
engine E9): the names a game's field texts (script messages, location
names) may use, each bound to a name slot, a variable, a term or a party
record role, and the fixed words ("terms") those texts and term bindings
expand.

    "placeholders": {"player": {"name": 7}, "coins": {"var": "coins"},
                     "rival": {"term": "rival"}, "lead": {"record": "nickname", "slot": 0}},
    "terms": {"rival": "Rowan", "creature": {"one": "Creature", "many": "Creatures"}}

A manifest with a "placeholders" key (even an empty one) makes field texts
markup: `{name}` is a placeholder, `{prompt}` / `{page}` are controls and
`{@concept}` a term; without it braces are plain characters. The engine's
script compiler is the authority: its FieldPlaceholders class checks the
whole set (kinds PLACEHOLDER_KINDS, extra keys PLACEHOLDER_EXTRA_KEYS,
name rules, limits, the code page, the record layout of the manifest's
"battle"); an edit it refuses is refused with its message. A placeholder
rename rewrites `{old}` in the sources' string literals; a placeholder or
term still used is not removed.

Edits change a core.scripts.ScriptProject's manifest (and, for a rename,
its source buffers). Each runs inside edit(project, label), which keeps an
undo history per project: undo() / redo() put the manifest and the
buffers back. Nothing here imports Qt.
"""
from __future__ import annotations

import copy
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from . import codepage, engine
from .document import DocumentError

if TYPE_CHECKING:
   from .scripts import ScriptProject

## A parsed JSON object.
JsonDict = dict[str, Any]
## One undo state: (label, manifest copy, source texts copy).
State = tuple[str, JsonDict, dict[str, str]]

## The manifest's placeholder bindings.
PLACEHOLDERS_KEY = "placeholders"
## The manifest's terms.
TERMS_KEY = "terms"
## The manifest's battle manifest (its record layout for record bindings).
BATTLE_KEY = "battle"
## A string literal of a source, from its opening quote.
STRING_LITERAL = re.compile(r'"(?:[^"\\\n]|\\.)*"')
## A term in markup, `{@concept}` or `{@concept:many}`.
TERM_MARKUP = re.compile(r"\{@([a-z_][a-z0-9_]*)(?::[a-z]+)?\}")
## Most undo steps kept per project.
HISTORY_LIMIT = 100


def _sc() -> Any:
   """!The engine's script compiler.
   @return module
   """
   return engine.tool("script_compiler")


def kinds() -> list[str]:
   """!The binding kinds (capsule::script::PlaceholderKind order).
   @return PLACEHOLDER_KINDS
   """
   return list(_sc().PLACEHOLDER_KINDS)


def extra_keys(kind: str) -> list[str]:
   """!The keys a binding of a kind may have besides its kind's.
   @param kind  one of kinds()
   @return names ("form" for term, "slot" for record)
   """
   return sorted(_sc().PLACEHOLDER_EXTRA_KEYS.get(kind, ()))


def max_name_length() -> int:
   """!The longest name slot (text_encoder.MAX_PLACEHOLDER_CODES).
   @return characters
   """
   return int(engine.tool("text_encoder").MAX_PLACEHOLDER_CODES)


def term_forms() -> list[str]:
   """!A term's forms.
   @return [TERM_ONE, TERM_MANY]
   """
   sc = _sc()
   return [sc.TERM_ONE, sc.TERM_MANY]


# -- undo history ------------------------------------------------------------------------------------------------------

class History:
   """!Undo and redo states of one ScriptProject's manifest and buffers."""

   def __init__(self) -> None:
      """!An empty history."""
      ## States before each edit (newest last).
      self.undo = []
      ## States undone (newest last).
      self.redo = []


## History by project (kept on the project object).
HISTORY_ATTR = "_placeholder_history"


def history(project: ScriptProject) -> History:
   """!A project's placeholder undo history.
   @param project  ScriptProject
   @return History (created on first use)
   """
   h = getattr(project, HISTORY_ATTR, None)
   if h is None:
      h = History()
      setattr(project, HISTORY_ATTR, h)
   return h


def _state(project: ScriptProject, label: str) -> State:
   """!The project's manifest and buffers now.
   @param project  ScriptProject
   @param label    undo label
   @return the state
   """
   return label, copy.deepcopy(project.manifest), dict(project.texts)


def _restore(project: ScriptProject, state: State) -> None:
   """!Puts a state back.
   @param project  ScriptProject
   @param state    the state
   @return None
   """
   _label, manifest, texts = state
   project.manifest.clear()
   project.manifest.update(copy.deepcopy(manifest))
   project.texts.clear()
   project.texts.update(texts)
   project.manifest_dirty = True


@contextmanager
def edit(project: ScriptProject, label: str) -> Iterator[None]:
   """!One undo step: an error inside puts the manifest and buffers back and is raised again.
   @param project  ScriptProject
   @param label    undo label
   @return context manager
   """
   before = _state(project, label)
   try:
      yield
   except BaseException:
      _restore(project, before)
      raise
   _label, manifest, texts = before
   # compared as JSON text: a move changes only the key order, which dict equality ignores
   if json.dumps(manifest) != json.dumps(project.manifest) or texts != project.texts:
      h = history(project)
      h.undo.append(before)
      del h.undo[:-HISTORY_LIMIT]
      h.redo.clear()
      project.manifest_dirty = True


def undo_label(project: ScriptProject) -> str | None:
   """!The label of the step undo() takes back.
   @param project  ScriptProject
   @return label, or None
   """
   h = history(project)
   return h.undo[-1][0] if h.undo else None


def undo(project: ScriptProject) -> bool:
   """!Takes the last placeholder edit back.
   @param project  ScriptProject
   @return True when there was one
   """
   h = history(project)
   if not h.undo:
      return False
   state = h.undo.pop()
   h.redo.append(_state(project, state[0]))
   _restore(project, state)
   return True


def redo(project: ScriptProject) -> bool:
   """!Does the last undone edit again.
   @param project  ScriptProject
   @return True when there was one
   """
   h = history(project)
   if not h.redo:
      return False
   state = h.redo.pop()
   h.undo.append(_state(project, state[0]))
   _restore(project, state)
   return True


# -- checking ----------------------------------------------------------------------------------------------------------

def _page(project: ScriptProject) -> Any:
   """!The game's code page (the engine's default outside a game).
   @param project  ScriptProject
   @return text_encoder.CodePage
   """
   try:
      return codepage.for_file(project.path)
   except DocumentError:
      return codepage.default_page()


def compiled(project: ScriptProject) -> tuple[Any, str | None]:
   """!The placeholders as the engine's script compiler reads them.
   @param project  ScriptProject
   @return (script_compiler.FieldPlaceholders or None, its message or None)
   """
   sc = _sc()
   m = project.manifest
   try:
      layout = None
      if isinstance(m.get(BATTLE_KEY), str):
         layout = sc.load_record_layout(project.path.parent / m[BATTLE_KEY])
      return sc.FieldPlaceholders(m, _page(project), layout), None
   except Exception as e:   # ScriptError, a battle manifest that cannot be read
      return None, str(e)


def _guarded(project: ScriptProject, change: Any) -> Any:
   """!Runs a change; refused when the placeholders compiled before and do not after.
   @param project  ScriptProject
   @param change   callable()
   @return what it returned
   @throws DocumentError with the compiler's message
   """
   _f, before = compiled(project)
   result = change()
   if before is None:
      _f, after = compiled(project)
      if after is not None:
         raise DocumentError(after)
   return result


# -- uses in the sources -----------------------------------------------------------------------------------------------

## [S2] The last literal spans found per source: rel -> (its text, the spans). A large game (an imported one: 519
## sources, 21 placeholders and terms) asked every source once per name; the spans are read once per text now.
_literal_cache: dict[str, tuple[str, list[tuple[int, int]]]] = {}


def _literals(text: str, rel: str) -> list[tuple[int, int]]:
   """!The spans of a source's string literals (from the engine's tokenizer; [S2] kept until the text changes).
   @param text  the source
   @param rel   its name
   @return [(start, end)] offsets in the text
   """
   cached = _literal_cache.get(rel)
   if cached is not None and (cached[0] is text or cached[0] == text):
      return cached[1]
   spans = _find_literals(text, rel)
   _literal_cache[rel] = (text, spans)
   return spans


def _find_literals(text: str, rel: str) -> list[tuple[int, int]]:
   """!The spans of a source's string literals, read by the engine's tokenizer.
   @param text  the source
   @param rel   its name
   @return [(start, end)] offsets in the text
   """
   sc = _sc()
   try:
      toks = sc.tokenize(text, rel)
   except sc.ScriptError:
      return []
   starts = [0]
   for line in text.split("\n"):
      starts.append(starts[-1] + len(line) + 1)
   out = []
   for t in toks:
      if t.kind != "string":
         continue
      at = starts[t.line - 1] + t.col - 1
      m = STRING_LITERAL.match(text, at)
      if m is not None:
         out.append((m.start(), m.end()))
   return out


def uses(project: ScriptProject, name: str, term: bool = False) -> list[str]:
   """!Where the sources' texts use a placeholder (`{name}`) or a term (`{@name}`).
   @param project  ScriptProject
   @param name     the placeholder or concept
   @param term     True for a term
   @return "FILE line N" per use
   """
   out = []
   for rel in project.sources:
      text = project.texts.get(rel)
      if text is None:
         continue
      for a, b in _literals(text, rel):
         literal = text[a:b]
         found = [m.group(1) for m in TERM_MARKUP.finditer(literal)] if term else \
            ([name] if "{" + name + "}" in literal else [])
         if name in found:
            line = text.count("\n", 0, a) + 1   # 1-based line of the literal
            out.append(f"{rel} line {line}")
   return out


# -- placeholders ------------------------------------------------------------------------------------------------------

def declared(project: ScriptProject) -> bool:
   """!Whether the manifest declares placeholders (field texts are markup).
   @param project  ScriptProject
   @return True with a "placeholders" key
   """
   return PLACEHOLDERS_KEY in project.manifest


def rows(project: ScriptProject) -> list[JsonDict]:
   """!The placeholders in declaration order.
   @param project  ScriptProject
   @return per placeholder: name, kind, value, extra ({form} / {slot}), cells (the most it prints; None when the
           set does not compile), uses (count in the sources)
   """
   field, _error = compiled(project)
   given = project.manifest.get(PLACEHOLDERS_KEY)
   out = []
   for name, b in (given.items() if isinstance(given, dict) else []):
      b = b if isinstance(b, dict) else {}
      kind = next((k for k in kinds() if k in b), None)
      out.append({"name": name, "kind": kind, "value": b.get(kind) if kind else None,
                  "extra": {k: v for k, v in b.items() if k != kind},
                  "cells": field.widths.get(name) if field is not None else None,
                  "uses": len(uses(project, name))})
   return out


def _bindings(project: ScriptProject) -> JsonDict:
   """!The manifest's placeholder object, created when missing (field texts become markup).
   @param project  ScriptProject
   @return the live dict
   """
   if not isinstance(project.manifest.get(PLACEHOLDERS_KEY), dict):
      project.manifest[PLACEHOLDERS_KEY] = {}
   return project.manifest[PLACEHOLDERS_KEY]


def _binding(kind: str, value: Any, extra: JsonDict | None) -> JsonDict:
   """!A binding object.
   @param kind   one of kinds()
   @param value  its value (name slot length, variable, concept, role)
   @param extra  "form" / "slot", or None
   @return the binding
   """
   if kind not in kinds():
      raise DocumentError(f"a placeholder binds to one of {', '.join(kinds())}, got {kind!r}")
   out = {kind: value}
   for k, v in (extra or {}).items():
      if k not in extra_keys(kind):
         raise DocumentError(f"a {kind} binding takes {', '.join(extra_keys(kind)) or 'no other keys'}, got {k!r}")
      if v is not None:
         out[k] = v
   return out


def set_markup(project: ScriptProject, on: bool) -> None:
   """!Turns field text markup on (an empty "placeholders") or off (refused while placeholders are declared).
   @param project  ScriptProject
   @param on       True for markup
   @return None
   """
   if on:
      _bindings(project)
      return
   if project.manifest.get(PLACEHOLDERS_KEY):
      raise DocumentError("remove the placeholders first (field texts use markup while they exist)")
   project.manifest.pop(PLACEHOLDERS_KEY, None)


def add_placeholder(project: ScriptProject, name: str, kind: str, value: Any, extra: JsonDict | None = None) -> None:
   """!Declares a placeholder (field texts become markup when they were not).
   @param project  ScriptProject
   @param name     its name (a lower-case identifier, not a control)
   @param kind     one of kinds()
   @param value    the kind's value
   @param extra    "form" (term) / "slot" (record), or None
   @return None
   """
   if not isinstance(name, str) or not name.strip():
      raise DocumentError("placeholder names can't be empty")
   name = name.strip()
   if name in (project.manifest.get(PLACEHOLDERS_KEY) or {}):
      raise DocumentError(f"there is already a placeholder {{{name}}}")
   binding = _binding(kind, value, extra)
   _guarded(project, lambda: _bindings(project).__setitem__(name, binding))


def set_placeholder(project: ScriptProject, name: str, kind: str, value: Any, extra: JsonDict | None = None) -> None:
   """!Changes what a placeholder is bound to.
   @param project  ScriptProject
   @param name     the placeholder
   @param kind     one of kinds()
   @param value    the kind's value
   @param extra    "form" / "slot", or None
   @return None
   """
   if name not in (project.manifest.get(PLACEHOLDERS_KEY) or {}):
      raise DocumentError(f"no placeholder {{{name}}}")
   binding = _binding(kind, value, extra)
   _guarded(project, lambda: _bindings(project).__setitem__(name, binding))


def remove_placeholder(project: ScriptProject, name: str) -> None:
   """!Removes a placeholder no text uses (markup stays on).
   @param project  ScriptProject
   @param name     the placeholder
   @return None
   """
   if name not in (project.manifest.get(PLACEHOLDERS_KEY) or {}):
      raise DocumentError(f"no placeholder {{{name}}}")
   used = uses(project, name)
   if used:
      raise DocumentError(f"{{{name}}} is still used: {', '.join(used)}")
   _bindings(project).pop(name)


def move_placeholder(project: ScriptProject, name: str, delta: int) -> bool:
   """!Moves a placeholder up or down (its index: script_ids.h PLACEHOLDER_<NAME>).
   @param project  ScriptProject
   @param name     the placeholder
   @param delta    -1 up, +1 down
   @return True when it moved
   """
   b = _bindings(project)
   names = list(b)
   if name not in names:
      raise DocumentError(f"no placeholder {{{name}}}")
   i = names.index(name)
   j = i + delta
   if not 0 <= j < len(names):
      return False
   names.insert(j, names.pop(i))
   ordered = {n: b[n] for n in names}
   b.clear()
   b.update(ordered)
   return True


def rename_placeholder(project: ScriptProject, old: str, new: str) -> int:
   """!Renames a placeholder; `{old}` in the sources' string literals follows.
   @param project  ScriptProject
   @param old      current name
   @param new      new name
   @return texts changed
   """
   b = _bindings(project)
   if old not in b:
      raise DocumentError(f"no placeholder {{{old}}}")
   if not isinstance(new, str) or not new.strip():
      raise DocumentError("placeholder names can't be empty")
   new = new.strip()
   if new in b:
      raise DocumentError(f"there is already a placeholder {{{new}}}")
   changed = 0

   def change() -> None:
      """!Renames the binding (keeping its place) and the texts.
      @return None
      """
      nonlocal changed
      ordered = {(new if n == old else n): v for n, v in b.items()}
      b.clear()
      b.update(ordered)
      for rel in project.sources:
         text = project.texts.get(rel)
         if text is None:
            continue
         out, last = [], 0
         for start, end in _literals(text, rel):
            literal = text[start:end]
            fixed = literal.replace("{" + old + "}", "{" + new + "}")
            changed += fixed != literal
            out += [text[last:start], fixed]
            last = end
         out.append(text[last:])
         project.texts[rel] = "".join(out)

   _guarded(project, change)
   return changed


# -- terms -------------------------------------------------------------------------------------------------------------

def term_rows(project: ScriptProject) -> list[JsonDict]:
   """!The terms.
   @param project  ScriptProject
   @return per concept: concept, one, many (None: no plural), bindings (placeholders bound to it), uses
           (`{@concept}` in the sources)
   """
   one, many = term_forms()
   given = project.manifest.get(TERMS_KEY)
   bound = {}
   for name, b in (project.manifest.get(PLACEHOLDERS_KEY) or {}).items():
      if isinstance(b, dict) and isinstance(b.get("term"), str):
         bound.setdefault(b["term"], []).append(name)
   out = []
   for concept, v in (given.items() if isinstance(given, dict) else []):
      out.append({"concept": concept, "one": v if isinstance(v, str) else (v or {}).get(one),
                  "many": None if isinstance(v, str) else (v or {}).get(many), "bindings": bound.get(concept, []),
                  "uses": len(uses(project, concept, term=True))})
   return out


def set_term(project: ScriptProject, concept: str, text: str, plural: str | None = None) -> None:
   """!Sets a term (a concept's word, with its plural or without).
   @param project  ScriptProject
   @param concept  the concept (a lower-case identifier)
   @param text     its word
   @param plural   its plural, or None
   @return None
   """
   if not isinstance(concept, str) or not re.fullmatch(r"[a-z_][a-z0-9_]*", concept.strip()):
      raise DocumentError(f"a concept is a lower-case identifier, got {concept!r}")
   if not isinstance(text, str) or not text:
      raise DocumentError("a term needs its word")
   one, many = term_forms()
   value: Any = text if not plural else {one: text, many: plural}

   def change() -> None:
      """!Writes the term.
      @return None
      """
      terms = project.manifest.get(TERMS_KEY)
      if not isinstance(terms, dict):
         terms = project.manifest[TERMS_KEY] = {}
      terms[concept.strip()] = value

   _guarded(project, change)


def remove_term(project: ScriptProject, concept: str) -> None:
   """!Removes a term nothing uses (no binding, no `{@concept}` in the sources).
   @param project  ScriptProject
   @param concept  the concept
   @return None
   """
   terms = project.manifest.get(TERMS_KEY)
   if not isinstance(terms, dict) or concept not in terms:
      raise DocumentError(f"no term {concept!r}")
   row = next(r for r in term_rows(project) if r["concept"] == concept)
   used = [f"placeholder {{{n}}}" for n in row["bindings"]] + uses(project, concept, term=True)
   if used:
      raise DocumentError(f"term {concept!r} is still used: {', '.join(used)}")
   del terms[concept]
   if not terms:
      del project.manifest[TERMS_KEY]


def lines(project: ScriptProject) -> list[str]:
   """!The placeholders and terms as text lines.
   @param project  ScriptProject
   @return lines
   """
   out = [f"markup: {'on' if declared(project) else 'off (braces are plain characters)'}"]
   for r in rows(project):
      extra = "".join(f", {k} {v}" for k, v in r["extra"].items())
      cells = f"{r['cells']} cells" if r["cells"] is not None else "?"
      out.append(f"{{{r['name']}}}: {r['kind']} {r['value']}{extra}; prints up to {cells}; {r['uses']} use(s)")
   for t in term_rows(project):
      plural = f" / {t['many']}" if t["many"] else ""
      out.append(f"term {t['concept']}: {t['one']}{plural}; {len(t['bindings'])} binding(s), {t['uses']} use(s)")
   _field, error = compiled(project)
   if error:
      out.append(f"error: {error}")
   return out
