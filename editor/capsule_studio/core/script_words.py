"""!The words of the .cscript language for the script editor's colours, completion and statement templates [S2].

Every list comes from the engine's compilers (tools/script_compiler.py, tools/route_compiler.py): their keyword set,
statement words (engine I4: I4_WORDS and the kind lists of each statement, MSGBOX_KINDS, MSG_FLAGS, TRANSITIONS,
TRIGGER_KINDS, CONDITION_KINDS, OBJECT_WORDS, ...; S4: C10's FACE_WORDS and LIFETIMES), and the route steps of the
route compiler's step table (its docstring, the one place the step words are listed; DIRECTIONS and OPTIONS are
exports). A word only the engine's parser spells (a statement's modifier such as `fade ... speed N swap`) is in
MODIFIERS here, and the tests compile every STATEMENT_TEMPLATES entry with the engine's compiler, so a template that
no longer parses fails a test.

completions() reads the text before the cursor (which block it is in: a script, a route or movement body, a
map_scripts table, the top level; the words of the statement so far) and offers the words that fit there,
including the names the last check declared (scripts, flags, variables, constants, movements, marts, route steps).

Qt-free; ui/editors/script.py (colours, completion popup) and the `script words` command use it.
"""
from __future__ import annotations

import re
import types
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from . import engine

## Statement modifiers the engine's parser spells inline (not exported): word -> the statements they follow.
MODIFIERS = {"all": ("lock", "release"), "on": ("visible",), "off": ("visible",), "speed": ("fade",),
             "swap": ("fade",), "repeat": ("route",), "skip": ("route",), "nowait": ("route",)}
## Statement templates (I4, D-29): word -> an example statement; NAME-like words are the declared names a template
## takes (the tests declare them: TEMPLATE_DECLARATIONS). Inserted by Script > Insert statement.
STATEMENT_TEMPLATES = {
   "lock": "lock all;", "release": "release all;", "wait_msg": "wait_msg;", "wait_state": "wait_state;",
   "remove": "remove 1;", "visible": "visible 1 off;", "set_template": "set_template 1 pos 3 4;",
   "door": "door open 1 2;", "weather": "weather set 3;", "fade": "fade to_black speed 2;",
   "set_metatile": "set_metatile 1 2 5 1;", "respawn": "respawn 1;", "set_warp": "set_warp dynamic town 1 2;",
   "sound": "sound se 9;", "wait_sound": "wait_sound se;", "mart": "mart shop_list;",
   "msg": 'msg "Hello" nowait;', "msgbox": 'msgbox npc "Hello";', "call": "call other loose;",
   "warp": "warp town 1 2 nowait;", "wait_moves": "wait_moves last;", "route": "route 1 walk_up nowait;",
   "override": "override apply SET_NAME;",   # S3 (DS1, D-30): a cell override set of the manifest's world
   "face": "face selected opposite_player;",   # S4 (C10): the talked-to object turns its back on the player
}
## S3: templates naming the manifest's world's data (their NAME word is a set of the world: the tests compile them
## against a world that has one).
WORLD_TEMPLATES = {"override": "SET_NAME"}
## The declarations the templates name (prepended when the tests compile them).
TEMPLATE_DECLARATIONS = "movement walk_up { up; in_place left 3; face original; }\nmart shop_list { 1, 2 }\n" \
                        "script other { return; }\n"
## Statement words that take an object first (self, player, a local ID or constant).
OBJECT_STATEMENTS = ("move", "face", "hide", "show", "route", "wait_moves", "place", "remove", "visible",
                     "set_template")
## Statement words whose next word is a script.
SCRIPT_STATEMENTS = ("call", "goto")
## Words before a statement's second operand: `route OBJ` then its body or a movement name, `set_warp KIND` then its
## map, `NAME (` (flag(, var(, script() then a name.
SECOND_OPERAND_AT = 2
## Shortest typed prefix the editor completes by itself (Ctrl+Space completes from nothing).
AUTO_PREFIX = 2
## The route step table's indent in the route compiler's docstring (a step line starts with it).
STEP_LINE_INDENT = "    "
## Columns between a step's syntax and its description in that table (two or more spaces).
STEP_DESCRIPTION_GAP = re.compile(r"\s{2,}")
## A word of the language (identifier).
WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
## Operators of two characters (one word each in a context's statement).
OPERATORS = ("->", "==", "!=", "<=", ">=", "&&", "||", "+=", "-=")
## Characters a backslash escape in a string takes (the backslash and the character).
ESCAPE_LENGTH = 2
## Context kinds of completions(): outside any block, a script body, a route / movement body, a map_scripts table,
## a mart list.
CONTEXT_KINDS = ("top", "script", "route", "map_scripts", "mart")
## Declared-name kinds completions() may offer (core.scripts.Outline kinds).
NAME_KINDS = ("script", "flag", "var", "const", "native", "map", "movement", "mart", "step", "override")
## S3: the name kind of the world's override sets (`override apply|clear NAME`; core.scripts.CheckResult).
OVERRIDE_NAMES = "override"


def compiler() -> types.ModuleType:
   """!The engine's script compiler module.
   @return module
   """
   return engine.tool("script_compiler")


def route_compiler() -> types.ModuleType:
   """!The engine's route compiler module.
   @return module
   """
   return engine.tool("route_compiler")


def _export(module: types.ModuleType, name: str, default: object = ()) -> object:
   """!An export of an engine module, or a default when the engine predates it.
   @param module   the module
   @param name     the export
   @param default  its stand-in
   @return the value
   """
   return getattr(module, name, default)


def statement_kinds() -> dict[str, list[str]]:
   """!The kind words each statement takes (its second word, or after its object), from the compiler's exports.
   @return statement word -> its kind words
   """
   sc = compiler()
   out: dict[str, list[str]] = {
      "door": list(_export(sc, "DOOR_KINDS")), "weather": list(_export(sc, "WEATHER_KINDS")),
      "fade": list(_export(sc, "FADE_KINDS")), "set_warp": list(_export(sc, "SET_WARP_KINDS")),
      "sound": list(_export(sc, "SOUND_KINDS")), "wait_sound": list(_export(sc, "SOUND_WAITS")),
      "set_template": list(_export(sc, "TEMPLATE_KINDS")), "msgbox": list(_export(sc, "MSGBOX_KINDS")),
      "msg": list(_export(sc, "MSG_FLAGS")), "warp": list(_export(sc, "TRANSITIONS")),
      # S3 (DS1): `override apply|clear NAME`, apply first (the compiler lists clear first: its byte order)
      "override": sorted(_export(sc, "OVERRIDE_KINDS")),
      # S4 (C10): `face OBJ down|up|left|right|player|self|opposite_player`
      "face": [str(d) for d in _export(sc, "DIRECTIONS")] + [str(w) for w in _export(sc, "FACE_WORDS", {})]}
   loose, nowait = _export(sc, "LOOSE_WORD", None), _export(sc, "WARP_NOWAIT_WORD", None)
   if loose:
      out["call"] = [str(loose)]
   if nowait:
      out["warp"].append(str(nowait))
   for word, statements in MODIFIERS.items():
      for s in statements:
         out.setdefault(s, []).append(word)
   # the engine's F1 / F2 statements: their kind words (FIELD_EFFECT_KINDS, ...)
   for word_export, kinds_export in (("FIELD_EFFECT_WORD", "FIELD_EFFECT_KINDS"),
                                     ("FIELD_ACTION_WORD", "FIELD_ACTION_KINDS"), ("FLIGHT_WORD", "FLIGHT_KINDS")):
      word = _export(sc, word_export, None)
      if word:
         out[str(word)] = [str(k) for k in _export(sc, kinds_export)]
   return {k: list(dict.fromkeys(v)) for k, v in out.items()}


def statement_words() -> list[str]:
   """!Words that start a statement: the compiler's keywords that do, its I4 statement words and the F1 / F2 ones.
   @return words
   """
   sc = compiler()
   declaration_only = {"flag", "var", "const", "native", "script", "map_scripts", "of", "else", "case", "default",
                       "not", "game", "cancel", "waits", "value", "yes", "no", "true", "false", "self", "player"}
   lifetimes = set(_export(sc, "LIFETIMES")) | set(_export(sc, "TYPES"))
   words = [w for w in sorted(sc.KEYWORDS) if w not in declaration_only and w not in lifetimes]
   words += [str(w) for w in _export(sc, "I4_WORDS")]
   for export in ("FIELD_EFFECT_WORD", "FIELD_ACTION_WORD", "FLIGHT_WORD", "DARKNESS_WORD", "ESCAPE_WORD"):
      word = _export(sc, export, None)
      if word:
         words.append(str(word))
   return list(dict.fromkeys(words))


def declaration_words() -> list[str]:
   """!Words that start a declaration (the top level): the compiler's own and I4's movement / mart / step.
   @return words
   """
   sc = compiler()
   words = ["flag", "var", "const", "native", "script", "map_scripts", "when"]
   for export in ("MOVEMENT_WORD", "MART_WORD", "STEP_WORD"):
      word = _export(sc, export, None)
      if word:
         words.append(str(word))
   return words


def trigger_kinds() -> list[str]:
   """!The map_scripts trigger kinds, in the engine's TriggerKind order (I4: on_resume, on_warp_into, ...).
   @return kinds
   """
   return [str(k) for k in compiler().TRIGGER_KINDS]


def condition_kinds() -> list[str]:
   """!The trigger kinds whose entries take a condition (`on_frame <cond> -> s`, I4 `on_warp_into <cond> -> s`).
   @return kinds
   """
   sc = compiler()
   return [str(k) for k in _export(sc, "CONDITION_KINDS", ("on_frame",))]


@dataclass
class RouteSteps:
   """!The route compiler's step words: each step word -> the words its first argument may be (empty: a number or a
   name)."""

   ## Step word -> argument words.
   steps: dict[str, list[str]] = field(default_factory=dict)

   def words(self) -> list[str]:
      """!The step words.
      @return words, in the table's order
      """
      steps = self.steps   # a local alias (Doxygen 1.12 reads a dataclass field used in a method as a new member)
      return list(steps)


def route_steps() -> RouteSteps:
   """!The route steps of the engine's route compiler (its step table, the module docstring's indented lines:
   `up | down | left | right [n]`, `face up | down | ... | original`, `in_place DIR [speed]`, `step NAME [arg]`).
   @return RouteSteps
   """
   rc = route_compiler()
   out = RouteSteps()
   doc = rc.__doc__ or ""
   in_table = False
   for line in doc.splitlines():
      if not line.startswith(STEP_LINE_INDENT) or not line.strip():
         if in_table and line.strip() and not line.startswith(STEP_LINE_INDENT):
            break   # the table ends at the next unindented paragraph
         continue
      in_table = True
      syntax = STEP_DESCRIPTION_GAP.split(line.strip())[0]
      parts = [p.strip() for p in syntax.split("|")]
      head = parts[0].split()
      named = all(len(p.split()) == len(head) and p.split()[-1].isupper() for p in parts)
      if len(parts) > 1 and (len(head) == 1 or named):
         # alternatives that are steps of their own: `random | toward | away` (the last may carry an argument:
         # `right [n]`), `set FLAG | clear FLAG`
         for p in parts:
            word = p.split()[0]
            if WORD.fullmatch(word):
               out.steps.setdefault(word, [])
         continue
      word = head[0]
      if not WORD.fullmatch(word):
         continue
      # a step word, then its first argument's alternatives (`face up | down | ...`, `in_place up | ...`); a lone
      # argument is a number or a name (`wait n`, `jump dx dy`)
      args = [head[1]] + [p.split()[0] for p in parts[1:]] if len(head) > 1 and len(parts) > 1 else []
      words = out.steps.setdefault(word, [])
      if not args and len(head) == SECOND_OPERAND_AT and words:
         args = [head[1]]   # one more word of a step that has word arguments (`face original`)
      words += [a for a in args if a.islower() and WORD.fullmatch(a) and a not in words]
   for d in rc.DIRECTIONS:
      out.steps.setdefault(str(d), [])
   for option in rc.OPTIONS:
      out.steps[str(option)] = out.steps.get(str(option)) or ["on", "off"]   # walk_anim on | off, ...
   return out


## S5: the engine header of move routes (its table's "Does" column: what each step does at run time).
ROUTE_HEADER = "capsule/script/route.h"
## S5: a row of route.h's step table: `/// | Op | Arguments | Does |`.
ROUTE_ROW = re.compile(r"^///\s*\|\s*(?P<ops>[^|]+?)\s*\|\s*(?P<args>[^|]*?)\s*\|\s*(?P<does>[^|]+?)\s*\|\s*$")
## S5 (engine N2): what a step does at run time that route.h's table does not say yet (its InPlace row still reads
## "stands"; N2 plays the walk animation in place).
RUNTIME_NOTES = {"in_place": "engine N2: the mover walks in place: its walk animation plays for the step's time"}
## S5: a CamelCase opcode's word boundaries (InPlace -> in_place).
CAMEL_BOUNDARY = re.compile(r"(?<=[a-z])(?=[A-Z])")


def route_step_help() -> dict[str, str]:
   """!S5: what each route step word does: its line of the route compiler's step table (the syntax and the
   description), the run-time behaviour of route.h's table for the opcode of the same name (`InPlace` -> `in_place`;
   N2: Speed applies to the walker's route steps too) and RUNTIME_NOTES.
   @return step word -> help text (lines)
   """
   rc = route_compiler()
   out: dict[str, list[str]] = {}
   words = route_steps().words()
   for line in (rc.__doc__ or "").splitlines():
      if not line.startswith(STEP_LINE_INDENT) or not line.strip():
         continue
      syntax = STEP_DESCRIPTION_GAP.split(line.strip())[0]
      for part in syntax.split("|"):
         w = part.split()[0] if part.split() else ""
         if w in words and line.strip() not in out.get(w, []):
            out.setdefault(w, []).append(line.strip())
   try:
      text = (engine.root() / "include" / ROUTE_HEADER).read_text(encoding="utf-8")
   except (OSError, engine.EngineNotFound):
      text = ""
   for line in text.splitlines():
      m = ROUTE_ROW.match(line.strip())
      if m is None:
         continue
      for op in m.group("ops").split("/"):
         w = CAMEL_BOUNDARY.sub("_", op.strip()).lower()
         if w in words:
            out.setdefault(w, []).append(f"runs: {m.group('does')}")
   for w, note in RUNTIME_NOTES.items():
      out.setdefault(w, []).append(note)
   return {w: "\n".join(v) for w, v in out.items()}


def word_help(text: str, word: str) -> str | None:
   """!S5: the help a word shows under the mouse: a route step's (route_step_help()) inside a route or movement block.
   @param text  the source up to the word
   @param word  the word
   @return help text, or None
   """
   if not word or context_at(text).kind != "route":
      return None
   return route_step_help().get(word)


def keyword_words() -> list[str]:
   """!Every word the editor colours as a keyword: the compiler's keywords, the statement and declaration words, the
   trigger kinds, the statements' kind words and the route steps (with their word arguments).
   @return words, without repeats
   """
   sc = compiler()
   words = sorted(sc.KEYWORDS) + statement_words() + declaration_words() + trigger_kinds()
   for kinds in statement_kinds().values():
      words += kinds
   for step, args in route_steps().steps.items():
      words += [step] + args
   words += [str(w) for w in _export(sc, "OBJECT_WORDS", {})]
   words += [str(w) for w in _export(sc, "LIFETIMES")]   # S4: declarations' lifetimes (C10 session)
   glitch = _export(sc, "GLITCH_WORD", None)
   if glitch:
      words.append(str(glitch))
   return [w for w in dict.fromkeys(words) if WORD.fullmatch(w)]


@dataclass
class Context:
   """!Where the cursor is, for completions()."""

   ## One of CONTEXT_KINDS.
   kind: str
   ## The current statement's words before the one being typed.
   words: list[str]
   ## The word being typed (may be empty).
   partial: str


def context_at(text: str) -> Context:
   """!The block and statement the end of a text is in (the text before the cursor). Strings and comments are
   skipped; a block's kind is told by the words before its '{' (`script NAME {`, `route OBJ {`, `movement NAME {`,
   `map_scripts NAME {`, `mart NAME {`; a block inside a script body is part of it).
   @param text  the source up to the cursor
   @return Context
   """
   stack: list[str] = []
   words: list[str] = []
   i = 0
   n = len(text)
   while i < n:
      c = text[i]
      if text.startswith("//", i):
         end = text.find("\n", i)
         i = n if end < 0 else end
         continue
      if text.startswith("/*", i):
         end = text.find("*/", i + len("/*"))
         i = n if end < 0 else end + len("*/")
         continue
      if c == '"':
         # a string: skip to its closing quote (backslash escapes kept)
         j = i + 1
         while j < n and text[j] != '"':
            j += ESCAPE_LENGTH if text[j] == "\\" else 1
         i = j + 1
         words.append('""')
         continue
      if c == "{":
         stack.append(_block_kind(stack, words))
         words = []
      elif c == "}":
         if stack:
            stack.pop()
         words = []
      elif c == ";":
         words = []
      elif c.isalnum() or c == "_":
         m = WORD.match(text, i)
         if m is None:   # a number
            j = i
            while j < n and (text[j].isalnum() or text[j] == "_"):
               j += 1
            words.append(text[i:j])
            i = j
            continue
         words.append(m.group())
         i = m.end()
         continue
      elif not c.isspace():
         two = text[i:i + len(OPERATORS[0])]
         if two in OPERATORS:
            words.append(two)
            i += len(two)
            continue
         words.append(c)
      i += 1
   partial = ""
   if words and text and (text[-1].isalnum() or text[-1] == "_") and WORD.fullmatch(words[-1]):
      partial = words.pop()
   kind = stack[-1] if stack else "top"
   return Context(kind, words, partial)


def _block_kind(stack: Sequence[str], words: Sequence[str]) -> str:
   """!The kind of a block a '{' opens.
   @param stack  the kinds of the blocks it is inside
   @param words  the words before the '{'
   @return one of CONTEXT_KINDS
   """
   sc = compiler()
   inside = stack[-1] if stack else "top"
   head = words[0] if words else ""
   if head == "route" or (inside == "top" and head == str(_export(sc, "MOVEMENT_WORD", "movement"))):
      return "route"
   if inside == "top" and head == "map_scripts":
      return "map_scripts"
   if inside == "top" and head == str(_export(sc, "MART_WORD", "mart")):
      return "mart"
   if inside in ("script", "route", "map_scripts", "mart"):
      return "script" if inside == "script" else inside
   return "script" if head == "script" else "top"


def completions(text: str, names: Mapping[str, Sequence[str]] | None = None) -> list[str]:
   """!The words that may come at the end of a text (the cursor), the typed part of a word included or not.
   @param text   the source up to the cursor
   @param names  declared names by kind (NAME_KINDS; core.scripts.Outline.names()), or None
   @return words starting with the typed part, in a useful order, without repeats
   """
   names = names or {}
   ctx = context_at(text)
   out = _candidates(ctx, names)
   return [w for w in dict.fromkeys(out) if w.startswith(ctx.partial) and w != ctx.partial]


def _names(names: Mapping[str, Sequence[str]], *kinds: str) -> list[str]:
   """!Declared names of some kinds.
   @param names  by kind
   @param kinds  the kinds
   @return the names
   """
   return [n for k in kinds for n in names.get(k, [])]


def _declaration_candidates(words: Sequence[str]) -> list[str]:
   """!S4: the words after a flag or variable declaration's name: `flag NAME : LIFETIME`, `var NAME : TYPE
   [LIFETIME]` (the compiler's LIFETIMES, C10 session; its TYPES).
   @param words  the declaration's words so far
   @return words
   """
   sc = compiler()
   lifetimes = [str(w) for w in _export(sc, "LIFETIMES")]
   types_ = [str(t) for t in _export(sc, "TYPES", {})]
   head = words[0] if words else ""
   if head not in ("flag", "var") or len(words) < SECOND_OPERAND_AT:
      return []
   if len(words) == SECOND_OPERAND_AT:
      return [":"]
   if head == "flag":
      return lifetimes if words[-1] == ":" else []
   if words[-1] == ":":
      return types_
   return lifetimes if words[-1] in types_ else []


def _candidates(ctx: Context, names: Mapping[str, Sequence[str]]) -> list[str]:
   """!The words that fit a context (before filtering by the typed part).
   @param ctx    the Context
   @param names  declared names by kind
   @return words
   """
   sc = compiler()
   words = ctx.words
   if ctx.kind == "top":
      if not words:
         return declaration_words()
      if words[0] == "when":
         return ["not", "game", str(_export(sc, "GLITCH_WORD", "glitch"))]
      return _declaration_candidates(words)
   if ctx.kind == "mart":
      return _names(names, "const")
   if ctx.kind == "map_scripts":
      if not words:
         return trigger_kinds()
      if words[-1] == "->":
         return _names(names, "script")
      if words[0] in condition_kinds():
         return ["flag", "var", "->"] + _names(names, "const")
      return ["->"]
   if ctx.kind == "route":
      steps = route_steps()
      if not words:
         return steps.words()
      step = words[0]
      if step in ("set", "clear"):
         return _names(names, "flag")
      if step == "step":
         return _names(names, "step")
      return steps.steps.get(step, []) if len(words) == 1 else []
   # a script body
   if not words:
      return statement_words() + list(STATEMENT_TEMPLATES)
   first = words[0]
   kinds = statement_kinds()
   if first in SCRIPT_STATEMENTS:
      return _names(names, "script") if len(words) == 1 else kinds.get(first, [])
   if words[-1] == "(" and len(words) >= SECOND_OPERAND_AT:
      return {"flag": _names(names, "flag"), "var": _names(names, "var"),
              "script": _names(names, "script")}.get(words[:-1][-1], [])
   if first == "override":   # S3: `override apply|clear NAME`, NAME a set of the manifest's world
      return kinds.get(first, []) if len(words) == 1 else _names(names, OVERRIDE_NAMES) \
         if len(words) == SECOND_OPERAND_AT else []
   if first == str(_export(sc, "MART_WORD", "mart")) and len(words) == 1:
      return _names(names, "mart")
   if first in OBJECT_STATEMENTS and len(words) == 1:
      objects = ["self", "player"] + [str(w) for w in _export(sc, "OBJECT_WORDS", {})]
      return objects + _names(names, "const")
   if first == "route" and len(words) == SECOND_OPERAND_AT:
      return ["{"] + _names(names, "movement")
   if first == "set_warp" and len(words) == SECOND_OPERAND_AT or first == "warp" and len(words) == 1:
      return _names(names, "map")
   if first in ("if", "while") or first in ("set", "clear"):
      return ["flag", "var"] + _names(names, "const")
   if first in kinds:
      return kinds[first] + _names(names, "const")
   return _names(names, "const")


def check_names(result: object) -> dict[str, list[str]]:
   """!S3: the names a check declared, by NAME_KINDS kind, for completions(): its outline's and the override sets of
   the manifest's world.
   @param result  core.scripts.CheckResult, or None
   @return {kind: names}
   """
   from . import scripts
   if result is None:
      return {}
   outline = result.outline
   names = {k: outline.names(k) for k in scripts.OUTLINE_KINDS}
   names[OVERRIDE_NAMES] = list(getattr(result, "override_sets", []))
   return names
