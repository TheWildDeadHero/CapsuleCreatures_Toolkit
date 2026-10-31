"""!The battle's messages (the battle manifest's "messages": {key: text}),
as the engine's battle compiler takes them (battlec/texts.py; engine C4).

Three kinds of key, in message id order:
  - required engine messages (REQUIRED_MESSAGES): the engine says them; they
    are always there and cannot be removed or renamed;
  - optional engine messages (OPTIONAL_MESSAGES): said only where the data
    or logic names them; added and removed like the game's own;
  - game messages (game_messages()): any other key, a lower-case
    identifier, declares a message of the battle's own after the engine's
    ids (at most MAX_MESSAGES ids in all). Effect logic (`say KEY`), the
    chart's tiers and above / below messages and the condition records'
    texts ({"message": KEY}) name them as they name the optional ones.

Every list here comes from the engine (no copy of its message table); the
texts are checked with the engine's encoder against the game's code page and
terms. A rename follows every use (the effect logic through core.logic, the
chart and the condition records); a message still used cannot be removed.
Functions that change a Document must be called inside doc.edit() (an edit
of either manifest of a project covers both).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import battle, codepage, engine, logic
from .document import DocumentError

if TYPE_CHECKING:
   from .document import Document

## One row of rows(): {"key", "kind" (REQUIRED | OPTIONAL | GAME), "id" (its message id, or None for an optional
## message the data leaves out), "given" (the data states it), "text" (or None), "args" (the placeholders it takes)}.
MessageRow = dict[str, Any]

## The manifest section.
MESSAGES_KEY = "messages"
## Kind of a message the engine always says.
REQUIRED = "required"
## Kind of an engine message said only where the data names it.
OPTIONAL = "optional"
## Kind of a message the battle declares itself.
GAME = "game"
## The effect logic's name list of messages (core.logic.name_lists()).
LOGIC_LIST = "messages"
## The chart (structure manifest) and its keys naming messages (core.structure.chart).
CHART_KEY = "chart"
## The chart's tier list.
TIERS_KEY = "tiers"
## A tier's / a condition text's key naming a message.
MESSAGE_FIELD = "message"
## A condition record's texts.
TEXTS_KEY = "texts"


def _bc() -> Any:
   """!The engine's battle compiler.
   @return the module
   """
   return engine.tool("battle_compiler")


def _texts() -> Any:
   """!Where the engine's message rules are read: the battle compiler's re-exports of battlec/texts.py
   (MESSAGE_KEY, RETIRED_MESSAGES; E13b).
   @return the module
   """
   return _bc()


def given(doc: Document) -> dict[str, Any]:
   """!The manifest's messages for reading.
   @param doc  any manifest Document of the battle
   @return {key: text} ({} when the section is missing or not an object)
   """
   msgs = battle.data_of(doc, MESSAGES_KEY).get(MESSAGES_KEY)
   return msgs if isinstance(msgs, dict) else {}


def _section(doc: Document) -> dict[str, Any]:
   """!The manifest's messages for changing (created when missing).
   @param doc  any manifest Document of the battle
   @return the live dict
   @throws DocumentError when the section is not an object
   """
   data = battle.data_of(doc, MESSAGES_KEY)
   msgs = data.setdefault(MESSAGES_KEY, {})
   if not isinstance(msgs, dict):
      raise DocumentError("the battle's messages must be an object {key: text}")
   return msgs


def engine_keys() -> list[str]:
   """!The engine's message keys, in Msg order (battlec.texts.MESSAGES).
   @return keys
   """
   return list(_bc().MESSAGES)


def max_game_messages() -> int:
   """!Most messages a battle declares itself: the message ids the engine's do not take (MAX_MESSAGES).
   @return count
   """
   return int(_bc().MAX_MESSAGES) - len(engine_keys())


def game_keys(doc: Document) -> list[str]:
   """!The messages the battle declares itself (the engine's game_messages()), in manifest order.
   @param doc  any manifest Document of the battle
   @return keys
   """
   return list(_bc().game_messages(given(doc)))


def kind_of(key: str) -> str:
   """!The kind of a message key.
   @param key  the key
   @return REQUIRED, OPTIONAL or GAME
   """
   bc = _bc()
   if key in bc.REQUIRED_MESSAGES:
      return REQUIRED
   return OPTIONAL if key in bc.OPTIONAL_MESSAGES else GAME


def args_of(key: str) -> list[str]:
   """!The placeholders a message takes: {user} and {target}, and the value an engine message carries
   (MESSAGE_ARGS: {move}, {value}, ...).
   @param key  the key
   @return names, sorted
   """
   bc = _bc()
   return sorted(set(bc.MESSAGE_BASE_ARGS) | set(bc.MESSAGE_ARGS.get(key, set())))


def rows(doc: Document) -> list[MessageRow]:
   """!Every message the data can have, in message id order: the engine's (an optional one the data leaves out
   has no id), then the battle's own.
   @param doc  any manifest Document of the battle
   @return MessageRow per key
   """
   msgs = given(doc)
   ids = _bc().declared_messages(msgs)
   out = []
   for i, key in enumerate(engine_keys() + game_keys(doc)):
      out.append({"key": key, "kind": kind_of(key), "id": i if ids[i] is not None else None, "given": key in msgs,
                  "text": msgs.get(key), "args": args_of(key)})
   return out


def absent_optional(doc: Document) -> list[str]:
   """!The optional engine messages the data leaves out (they can be added).
   @param doc  any manifest Document of the battle
   @return keys, in Msg order
   """
   msgs = given(doc)
   return [k for k in _bc().OPTIONAL_MESSAGES if k not in msgs]


def text_problem(doc: Document, key: str, text: Any) -> str | None:
   """!What the engine's text encoder says about a message text (its placeholders, terms, the code page).
   @param doc   any manifest Document of the battle
   @param key   the message key (its placeholders: args_of())
   @param text  the text
   @return the problem, or None when the engine takes it
   """
   bc = _bc()
   if not isinstance(text, str):
      return "a message is a text"
   try:
      page = codepage.for_file(doc.path) if doc.path is not None else codepage.default_page()
   except DocumentError:
      page = codepage.default_page()
   try:
      terms = bc.compile_terms(battle.data_of(doc, "terms").get("terms", {}), "terms")
   except bc.ManifestError:
      terms = bc.compile_terms({}, "terms")
   try:
      bc.encode(text, f"messages.{key}", set(args_of(key)), page, terms)
   except bc.ManifestError as e:
      return str(e)
   return None


def key_problem(doc: Document, key: Any, current: str | None = None) -> str | None:
   """!Whether a key can be a message the battle declares itself (a new one, or a rename of @p current).
   @param doc      any manifest Document of the battle
   @param key      the wanted key
   @param current  the message being renamed, or None
   @return the problem, or None
   """
   tx = _texts()
   if not isinstance(key, str) or not tx.MESSAGE_KEY.match(key):
      return f"a message of the battle's own needs a lower-case identifier for its key, got {key!r}"
   if key in tx.RETIRED_MESSAGES:
      return tx.RETIRED_MESSAGES[key]
   if key in engine_keys():
      return f"{key!r} is an engine message (add an optional one with its own key)"
   if key != current and key in given(doc):
      return f"there is already a message {key!r}"
   return None


# -- uses -------------------------------------------------------------------------------------------------------------

def _structure_uses(doc: Document, key: str, new: str | None = None) -> list[str]:
   """!Finds (and renames) a message in the structure: the chart's above / below messages and tiers, the condition
   records' texts, the recruit section's messages (G3), the step effects' messages (C8).
   @param doc  any manifest Document of the battle (changes happen in the edit running on it)
   @param key  the message
   @param new  new key, or None to only look
   @return "where" strings
   """
   found = []
   ch = battle.data_of(doc, CHART_KEY).get(CHART_KEY)
   if isinstance(ch, dict):
      above_below = ch.get(MESSAGES_KEY)
      if isinstance(above_below, dict):
         for option, value in above_below.items():
            if value == key:
               found.append(f"chart: messages.{option}")
               if new is not None:
                  above_below[option] = new
      for tier in ch.get(TIERS_KEY) or []:
         if isinstance(tier, dict) and tier.get(MESSAGE_FIELD) == key:
            found.append(f"chart: tier {tier.get('name')!r}")
            if new is not None:
               tier[MESSAGE_FIELD] = new
   from .structure import conditions   # local: core.structure imports core modules
   for kind in conditions.kinds():
      lst = conditions.list_key(kind)
      for e in battle.data_of(doc, lst).get(lst) or []:
         texts = e.get(TEXTS_KEY) if isinstance(e, dict) else None
         if not isinstance(texts, dict):
            continue
         for slot, value in texts.items():
            if isinstance(value, dict) and value.get(MESSAGE_FIELD) == key:
               found.append(f"{kind} {e.get('name')!r}: text {slot}")
               if new is not None:
                  value[MESSAGE_FIELD] = new
   # G3: the recruit section's messages (core.structure.recruit); C8: the step effects' (core.structure.step_effects)
   from .structure import combination, recruit, step_effects
   # B1: the combination methods' messages
   return found + recruit.message_uses(doc, key, new) + step_effects.message_uses(doc, key, new) + \
      combination.message_uses(doc, key, new)


def uses(doc: Document, key: str) -> list[str]:
   """!What names a message: effect logic (`say`), the chart, the condition records.
   @param doc  any manifest Document of the battle
   @param key  the message
   @return "where" strings
   @throws DocumentError when an effect source does not parse
   """
   return logic.per_owner(logic.references(doc, (LOGIC_LIST,), key)) + _structure_uses(doc, key)


# -- editing ----------------------------------------------------------------------------------------------------------

def set_text(doc: Document, key: str, text: str) -> None:
   """!Sets a message's text (an optional engine message the data leaves out is added).
   @param doc   any manifest Document of the battle
   @param key   an engine message, or one the battle declares
   @param text  the text (checked by the engine's encoder)
   @return None
   @throws DocumentError for an unknown key or a text the engine refuses
   """
   if key not in engine_keys() and key not in given(doc):
      raise DocumentError(f"no message {key!r} (add a message of the battle's own first)")
   problem = text_problem(doc, key, text)
   if problem is not None:
      raise DocumentError(problem)
   _section(doc)[key] = text


def add(doc: Document, key: str, text: str | None = None) -> str:
   """!Adds a message: an optional engine message the data leaves out, or one the battle declares itself (after the
   others: the next message id).
   @param doc   any manifest Document of the battle
   @param key   the key
   @param text  its text, or None (an engine message: the Blank template's text; one of the battle's: empty)
   @return the key
   @throws DocumentError for a taken or unusable key, a full message table or a text the engine refuses
   """
   key = key.strip() if isinstance(key, str) else key
   if key in engine_keys():
      if kind_of(key) == REQUIRED or key in given(doc):
         raise DocumentError(f"the data already has the message {key!r}")
   else:
      problem = key_problem(doc, key)
      if problem is not None:
         raise DocumentError(problem)
      most = max_game_messages()
      if len(game_keys(doc)) >= most:
         raise DocumentError(f"a battle declares at most {most} messages of its own (message ids up to "
                             f"{_bc().MAX_MESSAGES - 1})")
   value = text if text is not None else battle.DEFAULT_MESSAGES.get(key, "")
   problem = text_problem(doc, key, value)
   if problem is not None:
      raise DocumentError(problem)
   _section(doc)[key] = value
   return key


def remove(doc: Document, key: str) -> None:
   """!Removes a message (not a required engine message; refused while something names it).
   @param doc  any manifest Document of the battle
   @param key  the key
   @return None
   @throws DocumentError when it is required, missing or still used
   """
   if key not in given(doc):
      raise DocumentError(f"no message {key!r}")
   if kind_of(key) == REQUIRED:
      raise DocumentError(f"{key!r} is a message the engine always says (it cannot be removed)")
   used = uses(doc, key)
   if used:
      raise DocumentError(f"the message {key!r} is still used by: {', '.join(used)}")
   del _section(doc)[key]


def rename(doc: Document, old: str, new: str) -> list[str]:
   """!Renames a message the battle declares itself; effect logic, the chart and the condition records naming it
   follow (one undo step with the edit running on @p doc). It keeps its place (its message id).
   @param doc  any manifest Document of the battle
   @param old  the key
   @param new  the new key
   @return "where" strings of the uses that followed
   @throws DocumentError for an engine message, a missing key or an unusable new key
   """
   new = new.strip() if isinstance(new, str) else new
   if old not in given(doc) or kind_of(old) != GAME:
      raise DocumentError(f"{old!r} is not a message of the battle's own (engine messages keep their keys)")
   if new == old:
      return []
   problem = key_problem(doc, new, old)
   if problem is not None:
      raise DocumentError(problem)
   followed = logic.references(doc, (LOGIC_LIST,), old, new, "Rename message")
   followed += _structure_uses(doc, old, new)
   msgs = _section(doc)
   items = [(new if k == old else k, v) for k, v in msgs.items()]   # the same order: the same message ids
   msgs.clear()
   msgs.update(items)
   return followed
