"""!The ruleset expression language as the studio's formula editors show it
(engine E13a): the Formulas page, the pipeline steps and the generation
list's derived expressions all write expressions of the engine's
tools/ruleset_compiler.py, which stays the one authority (its tokenizer,
operator levels, functions and helpers are read from it, never copied).

    if((seed_lo & BYTE_MASK) < species.gender_ratio, FEMALE, MALE)

What it offers (no Qt):
- the operator levels loosest first (Parser.LEVELS, then the unary
  operators) and their text for tool tips: since E13a the bit operators
  & | ^ and the shifts << >> bind tighter than the comparisons (as in Rust
  and Python, not C), so `a & MASK == 0` reads as `(a & MASK) == 0`;
- spans(): the expression cut into classified pieces with the engine's
  TOKEN pattern (numbers, inputs, species fields `species.NAME`, constants,
  functions, bit operators, other operators, unknown names, characters
  outside the language) for the editors' colours;
- Names: the inputs, constants and functions an expression of one place may
  use (formula_names(), pipeline_names(); core.structure.progression gives
  the derived expressions' own), and completion_words() of them;
- check(): the engine's own parse of an expression against those names (its
  RulesetError message, e.g. an unknown name or a shift amount outside
  [0, SHIFT_MAX] once the build analyses it);
- input_name_error(): why the engine refuses a ruleset input or a named
  formula's argument name (E13a: an identifier; a dotted `species.NAME` is
  the derived expressions' own input).
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, NamedTuple

from . import engine

if TYPE_CHECKING:
   from .battle import BattleProject

## Span kind: an integer literal.
KIND_NUMBER = "number"
## Span kind: an input (formula input, pipeline input or variable, record role).
KIND_INPUT = "input"
## Span kind: a species field (`species.NAME`, derived expressions).
KIND_FIELD = "species_field"
## Span kind: a constant (the ruleset's, the battle's).
KIND_CONSTANT = "constant"
## Span kind: a function or helper call.
KIND_FUNCTION = "function"
## Span kind: a bit operator (& | ^ ~) or a shift (<< >>).
KIND_BIT = "bit_operator"
## Span kind: any other operator or punctuation.
KIND_OPERATOR = "operator"
## Span kind: a name the place does not know.
KIND_UNKNOWN = "unknown"
## Span kind: a character outside the language.
KIND_INVALID = "invalid"
## The tree node of the unary bit operator (ruleset_compiler.UNARY_OPERATORS: ~ makes "inv", E13a).
INVERT_NODE = "inv"
## Text joining the operators of one precedence level.
LEVEL_JOIN = " "
## Text joining the precedence levels (loosest first).
LEVELS_JOIN = " ; "
## Groups of the engine's TOKEN pattern: number, name, two-character operator, one character.
NUMBER_GROUP, NAME_GROUP, OP2_GROUP, OP1_GROUP = 1, 2, 3, 4
## Opening parenthesis (a name before one is a call).
CALL_OPEN = "("
## Where check() says an expression is (the engine's messages start with it).
CHECK_WHERE = "expression"


class Span(NamedTuple):
   """!One classified piece of an expression."""
   ## First character.
   start: int
   ## One past the last character.
   end: int
   ## One of the KIND_* words.
   kind: str


@dataclass
class Names:
   """!What an expression of one place may name."""
   ## Input names (formula inputs, pipeline inputs and variables, record roles, `species.NAME`).
   inputs: list[str] = field(default_factory=list)
   ## Constant names.
   constants: list[str] = field(default_factory=list)
   ## Callable names -> argument count.
   functions: dict[str, int] = field(default_factory=dict)


def _rc() -> Any:
   """!The engine's ruleset compiler.
   @return module
   """
   return engine.tool("ruleset_compiler")


# -- the language ------------------------------------------------------------------------------------------------------

def binary_levels() -> list[list[str]]:
   """!The binary operator levels, loosest first (the engine's Parser.LEVELS).
   @return a copy
   """
   return [list(level) for level in _rc().Parser.LEVELS]


def unary_operators() -> list[str]:
   """!The unary operators of the ruleset parser (the engine's UNARY_OPERATORS, Parser.unary(): - ! ~).
   @return operators
   """
   return list(_rc().UNARY_OPERATORS)


def precedence() -> list[list[str]]:
   """!Every operator level, loosest first: the binary levels, then the unary operators (tightest).
   @return levels
   """
   return binary_levels() + [unary_operators()]


def precedence_text() -> str:
   """!The operator levels as one line ("|| ; && ; == != ; ... ; - ! ~"), for tool tips and notes.
   @return text
   """
   return LEVELS_JOIN.join(LEVEL_JOIN.join(level) for level in precedence())


def bit_operators() -> list[str]:
   """!The bit operators and shifts (E13a: the engine's BIT_OPS, SHIFT_OPS and ~).
   @return operators
   """
   rc = _rc()
   invert = [op for op, node in rc.UNARY_OPERATORS.items() if node == INVERT_NODE]
   return list(rc.BIT_OPS) + list(rc.SHIFT_OPS) + invert


def shift_max() -> int:
   """!The largest shift amount the engine allows (int32: SHIFT_MAX).
   @return the amount
   """
   return int(_rc().SHIFT_MAX)


def functions() -> dict[str, int]:
   """!The language's functions and their argument counts (the engine's FUNCTIONS).
   @return a copy
   """
   return dict(_rc().FUNCTIONS)


def helpers() -> dict[str, int]:
   """!The pipeline helpers and their argument counts (the engine's HELPERS; pipelines only).
   @return a copy
   """
   return dict(_rc().HELPERS)


def species_prefix() -> str:
   """!The prefix of a species field in a derived expression (the engine's SPECIES_PREFIX).
   @return "species."
   """
   return str(engine.tool("battle_compiler").SPECIES_PREFIX)


def input_name_error(name: Any) -> str | None:
   """!Why the engine refuses a name as a ruleset input or a named formula's argument (E13a INPUT_NAME: an
   identifier of letters, digits and _; a dotted name is a derived expression's own input).
   @param name  the name
   @return the reason, or None when it is fine
   """
   if isinstance(name, str) and _rc().INPUT_NAME.fullmatch(name):
      return None
   return f"input {name!r}: must be an identifier (letters, digits, _)"


# -- names of a place --------------------------------------------------------------------------------------------------

def ruleset_constants(project: BattleProject | None) -> list[str]:
   """!The ruleset's own constants.
   @param project  BattleProject, or None
   @return names
   """
   given = project.ruleset.data.get("constants") if project is not None else None
   return [str(k) for k in given] if isinstance(given, dict) else []


def battle_constants() -> list[str]:
   """!The constants the battle rules give pipelines and derived expressions (the engine's BATTLE_CONSTANTS).
   @return names
   """
   return list(_rc().BATTLE_CONSTANTS)


def _named_formula_args(project: BattleProject | None) -> dict[str, int]:
   """!The ruleset's named formulas and their argument counts (pipelines call them).
   @param project  BattleProject, or None
   @return name -> count
   """
   if project is None:
      return {}
   from . import battle   # local: core.battle imports the structure modules
   out = {}
   for name in battle.named_formulas(project.ruleset):
      args = battle.formula_entry(project.ruleset, name).get("args")
      out[name] = len(args) if isinstance(args, list) else 0
   return out


def formula_names(project: BattleProject | None, slot: str) -> Names:
   """!What a ruleset formula may name: its inputs, the ruleset's constants and the language's functions.
   @param project  BattleProject, or None
   @param slot     formula slot, named formula or stat formula
   @return Names
   """
   inputs = [n for n, _rng in project.formula_inputs(slot)] if project is not None else []
   return Names(inputs, ruleset_constants(project), functions())


def pipeline_names(project: BattleProject | None, pipeline: str, upto: int | None = None) -> Names:
   """!What a pipeline step may name: the pipeline's inputs, the variables of the steps before it, the ruleset's
   and the battle's constants, the functions, the helpers and the named formulas.
   @param project   BattleProject, or None
   @param pipeline  pipeline name
   @param upto      the step's index (the variables set before it), or None for every step's variable
   @return Names
   """
   from . import pipelines   # local: core.pipelines imports core.battle
   inputs = pipelines.pipeline_inputs(pipeline)
   steps = pipelines.shown_steps(project.ruleset, pipeline) if project is not None else []
   for step in steps[:upto] if upto is not None else steps:
      for key in ("let", "roll"):
         var = step.get(key) if isinstance(step, dict) else None
         if isinstance(var, str) and var not in inputs:
            inputs.append(var)
   return Names(inputs, ruleset_constants(project) + battle_constants(),
                {**functions(), **helpers(), **_named_formula_args(project)})


def completion_words(names: Names) -> list[str]:
   """!What an expression field completes: the inputs, the constants and the callable names.
   @param names  Names
   @return words, without repeats, in that order
   """
   out: list[str] = []
   for w in list(names.inputs) + list(names.constants) + list(names.functions):
      if w not in out:
         out.append(w)
   return out


# -- reading an expression ---------------------------------------------------------------------------------------------

def _next_is_call(text: str, at: int) -> bool:
   """!Whether a "(" follows a position (spaces skipped).
   @param text  the expression
   @param at    position after a name
   @return True for a call
   """
   rest = text[at:].lstrip()
   return rest.startswith(CALL_OPEN)


def _name_kind(name: str, call: bool, names: Names | None) -> str:
   """!The kind of a name.
   @param name   the name
   @param call   True when a "(" follows it
   @param names  what the place may name, or None (every name is fine; a dotted one is a species field)
   @return KIND_*
   """
   if call:
      return KIND_FUNCTION if names is None or name in names.functions else KIND_UNKNOWN
   field_name = name.startswith(species_prefix())
   if names is None:
      return KIND_FIELD if field_name else KIND_INPUT
   if name in names.inputs:
      return KIND_FIELD if field_name else KIND_INPUT
   if name in names.constants:
      return KIND_CONSTANT
   return KIND_UNKNOWN


def spans(text: str, names: Names | None = None) -> list[Span]:
   """!An expression cut into classified pieces with the engine's TOKEN pattern (spaces are left out).
   @param text   the expression
   @param names  what the place may name (an unknown name is KIND_UNKNOWN), or None
   @return spans in text order
   """
   rc = _rc()
   bits = set(bit_operators())
   out = []
   pos = 0
   while pos < len(text):
      m = rc.TOKEN.match(text, pos)
      if m is None or m.end() == pos:
         out.append(Span(pos, len(text), KIND_INVALID))
         break
      groups = m.groups()
      start = m.start(m.lastindex) if m.lastindex else m.end()
      if groups[NUMBER_GROUP - 1] is not None:
         out.append(Span(start, m.end(), KIND_NUMBER))
      elif groups[NAME_GROUP - 1] is not None:
         name = groups[NAME_GROUP - 1]
         out.append(Span(start, m.end(), _name_kind(name, _next_is_call(text, m.end()), names)))
      elif groups[OP2_GROUP - 1] is not None:
         op = groups[OP2_GROUP - 1]
         out.append(Span(start, m.end(), KIND_BIT if op in bits else KIND_OPERATOR))
      elif groups[OP1_GROUP - 1] is not None:
         op = groups[OP1_GROUP - 1]
         if op.isspace():
            pass   # trailing spaces the pattern did not skip
         elif op not in rc.SINGLE_OPS:
            out.append(Span(start, m.end(), KIND_INVALID))
         else:
            out.append(Span(start, m.end(), KIND_BIT if op in bits else KIND_OPERATOR))
      pos = m.end()
   return out


def check(text: str, names: Names, constants: Mapping[str, int] | None = None) -> str | None:
   """!Parses an expression with the engine's parser against the names of its place (the interval analysis, which
   bounds shifts and overflow, runs when the data compiles).
   @param text       the expression
   @param names      what the place may name
   @param constants  constant values (default: 0 for each of names.constants; only their names matter here)
   @return the engine's message, or None when it parses
   """
   rc = _rc()
   values = dict(constants) if constants is not None else {c: 0 for c in names.constants}
   extra = {k: v for k, v in names.functions.items() if k not in rc.FUNCTIONS}
   try:
      rc.parse(text, list(names.inputs), values, CHECK_WHERE, extra)
   except rc.RulesetError as e:
      return str(e)
   return None


def unknown_names(text: str, names: Names) -> list[str]:
   """!The names an expression uses that its place does not know.
   @param text   the expression
   @param names  what the place may name
   @return names in text order, without repeats
   """
   out: list[str] = []
   for s in spans(text, names):
      word = text[s.start:s.end]
      if s.kind == KIND_UNKNOWN and word not in out:
         out.append(word)
   return out


def words_of(text: str, kinds: Iterable[str]) -> list[str]:
   """!The pieces of an expression of some kinds (no names checked: a dotted name is a species field).
   @param text   the expression
   @param kinds  KIND_* words
   @return the pieces' text, in text order
   """
   wanted = set(kinds)
   return [text[s.start:s.end] for s in spans(text) if s.kind in wanted]
