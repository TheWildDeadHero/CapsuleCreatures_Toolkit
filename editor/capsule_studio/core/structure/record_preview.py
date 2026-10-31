"""!Previews of a creature record's derived roles and of a record transfer
(engine E13a), over the engine's Python mirrors of what the engine does:

- derived_rows(): every derived generation entry's value for a record the
  editor types in (the stored roles its expressions read, and a species
  whose fields they read): battlec.progression.derived_values() is what
  battle::record_value() reads (an unstored role, or a role the layout
  leaves out, computed on read) and rederive() what battle::rederive()
  writes into a stored derived role;
- transfer_preview(): the same record exported by a sending battle data (this
  one by default, or another game's battle.json) in the canonical transfer
  form and imported here with tools/record_transfer.py import_rederived()
  (= battle::import_record(): the import, then the derived roles the record
  did not hold re-derived; the roles it held keep the sender's values).

The battle data must compile (the previews read the compiled data, unsaved
edits included: BattleProject.compile()); every error comes back as the
engine's message.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

from .. import engine
from ..document import DocumentError

if TYPE_CHECKING:
   from ..battle import BattleProject

## A parsed JSON object.
JsonDict = dict[str, Any]
## A record dict (tools/record_transfer.py unpack() form): role -> int, list or {stat: int}.
RecordDict = dict[str, Any]

## The role holding a record's species (record_inputs() reads the species' fields through it).
SPECIES_ROLE = "species_key"
## The compiled entry kind of a derived entry (the engine's GEN_KINDS word).
DERIVED_KIND = "derived"
## How a derived role is read: the record holds it (rederive() writes it).
STATE_STORED = "stored"
## How a derived role is read: an unstored custom role (computed on read, E13a).
STATE_UNSTORED = "unstored"
## How a derived role is read: an engine role the layout leaves out (computed on read).
STATE_NOT_HELD = "not held"
## Location the transfer compile names.
WHERE = "preview"


class DerivedRow(TypedDict):
   """!One derived generation entry as the preview shows it."""
   ## Generation entry index.
   index: int
   ## Role it fills.
   role: str
   ## The expression.
   expr: str
   ## STATE_STORED, STATE_UNSTORED or STATE_NOT_HELD.
   state: str
   ## What battle::record_value() reads (derived_values()).
   value: Any
   ## What battle::rederive() writes (stored roles), else None.
   rederived: Any


def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


def compiled_of(project: BattleProject) -> JsonDict:
   """!The compiled battle data (unsaved edits included).
   @param project  BattleProject
   @return compile_battle() result
   @throws DocumentError with the compiler's message when it does not compile
   """
   compiled, error = project.compile()
   if compiled is None:
      raise DocumentError(f"the battle data does not compile: {error}")
   return compiled


def _derived_entries(compiled: JsonDict) -> list[tuple[int, JsonDict]]:
   """!The compiled derived generation entries.
   @param compiled  compile_battle() result
   @return [(index, entry)]
   """
   kinds = list(_bc().GEN_KINDS)
   return [(k, e) for k, e in enumerate(compiled["rules"]["progress"]["generation"])
           if kinds[e["kind"]] == DERIVED_KIND]


def input_roles(project: BattleProject) -> list[str]:
   """!The stored single-element roles the derived expressions read (32-bit ones once, not as NAME_hi /
   NAME_lo), in record order: what a preview record needs typed in.
   @param project  BattleProject
   @return role names ([] when the data does not compile)
   """
   compiled, _error = project.compile()
   if compiled is None:
      return []
   inputs = _bc().derived_inputs(compiled["layout"])
   used: set[str] = set()
   for _k, e in _derived_entries(compiled):
      used.update(e["formula"]["used"])
   out = []
   for name, (_rid, _shift, _mask, half) in inputs.items():
      role = name.rsplit("_", 1)[0] if half else name
      if name in used and role not in out and role != SPECIES_ROLE:
         out.append(role)
   return out


def role_max(project: BattleProject, role: str) -> int:
   """!The highest value of a role of the compiled layout.
   @param project  BattleProject
   @param role     role name
   @return 2^width - 1
   """
   compiled = compiled_of(project)
   return int(_bc().role_max_value(compiled["layout"], role))


def species_key(compiled: JsonDict, species: str | None) -> int | None:
   """!A species' key in compiled data.
   @param compiled  compile_battle() result
   @param species   species name, or None
   @return the key, or None when there is no such species
   """
   return next((int(s["key"]) for s in compiled["species"] if s["name"] == species), None)


def record_of(compiled: JsonDict, species: str | None, values: Mapping[str, int]) -> RecordDict:
   """!A record dict of typed-in role values and a species.
   @param compiled  compile_battle() result
   @param species   species name, or None (no species_key: every field reads its default)
   @param values    role -> value
   @return record dict
   @throws DocumentError for an unknown species
   """
   out: RecordDict = dict(values)
   if species is not None:
      key = species_key(compiled, species)
      if key is None:
         raise DocumentError(f"no species {species!r}")
      out[SPECIES_ROLE] = key
   return out


def _state(layout: JsonDict, role: str) -> str:
   """!How a derived role is read.
   @param layout  compiled layout
   @param role    role name
   @return STATE_*
   """
   if _bc().role_info(layout, role) is not None:
      return STATE_STORED
   return STATE_UNSTORED if role in layout.get("unstored_ids", {}) else STATE_NOT_HELD


def derived_rows(project: BattleProject, species: str | None, values: Mapping[str, int]) -> list[DerivedRow]:
   """!Every derived entry's value for a record: derived_values() (what battle::record_value() reads) and, for a
   stored role, rederive() (what battle::rederive() writes; later entries read the roles re-derived before them).
   @param project  BattleProject
   @param species  species name, or None
   @param values   stored role -> value (roles left out read 0)
   @return one row per derived entry, in generation order
   @throws DocumentError when the data does not compile or the evaluator refuses
   """
   bc = _bc()
   compiled = compiled_of(project)
   record = record_of(compiled, species, values)
   try:
      read = bc.derived_values(compiled, record)
      written = bc.rederive(compiled, record)
   except Exception as e:   # the evaluator's RulesetError (division by zero), odd values
      raise DocumentError(str(e)) from None
   out = []
   for k, e in _derived_entries(compiled):
      state = _state(compiled["layout"], e["role"])
      out.append(DerivedRow(index=k, role=e["role"], expr=e["formula"]["expr"], state=state,
                            value=read.get(e["role"]),
                            rederived=written.get(e["role"]) if state == STATE_STORED else None))
   return out


def _sender(project: BattleProject, sender: str | Path | None) -> JsonDict:
   """!The sending battle data, compiled.
   @param project  BattleProject (the sender when sender is None)
   @param sender   another game's battle.json, or None
   @return compile_battle() result
   @throws DocumentError when it does not compile
   """
   if sender is None:
      return compiled_of(project)
   try:
      return _bc().compile_battle(Path(sender))
   except Exception as e:   # ManifestError, OSError, odd data
      raise DocumentError(f"the sending battle data {Path(sender).name}: {e}") from None


def _table(compiled: JsonDict, where: str) -> JsonDict:
   """!The transfer table of compiled data (tools/battlec/transfer.py compile_transfer()).
   @param compiled  compile_battle() result
   @param where     location
   @return the table
   """
   return _bc().compile_transfer(compiled["layout"], compiled["stats"], where)


def _held_values(table: JsonDict, values: Mapping[str, Any]) -> RecordDict:
   """!The typed-in values of the roles a table's layout holds (the others are not in the sender's record).
   @param table   transfer table
   @param values  role -> value
   @return record dict
   """
   lay = table["layout"]
   return {k: v for k, v in values.items() if _bc().role_info(lay, k) is not None}


def transfer_preview(project: BattleProject, species: str | None, values: Mapping[str, int],
                     sender: str | Path | None = None) -> JsonDict:
   """!A record sent by a battle data and imported here (tools/record_transfer.py import_rederived(): the import,
   then the derived roles the record did not hold re-derived; battle::import_record()).
   @param project  BattleProject (the receiver)
   @param species  species name (the sender's species of that name), or None
   @param values   role -> value of the sent record (roles the sender's layout does not hold are left out)
   @param sender   another game's battle.json, or None for this battle data (the canonical form of its own record)
   @return {"record": imported record dict, "flags": flag names, "received": roles the record held,
           "rederived": derived roles the import re-derived, "bytes": transfer size, "sent": the sent record dict}
   @throws DocumentError when either data does not compile or the transfer is refused
   """
   rt = engine.tool("record_transfer")
   receiver = compiled_of(project)
   sent_from = _sender(project, sender)
   try:
      sender_table = _table(sent_from, WHERE)
      receiver_table = _table(receiver, WHERE)
      sent = _held_values(sender_table, record_of(sent_from, species, values))
      data = rt.export_record(sender_table, sent)
      received: set[str] = set()
      plain, _flags = rt.import_record(receiver_table, data, received)
      record, flags = rt.import_rederived(receiver_table, data, receiver)
   except DocumentError:
      raise
   except Exception as e:   # TransferError, ValueError (a value the layout cannot hold), ManifestError
      raise DocumentError(str(e)) from None
   rederived = [e["role"] for _k, e in _derived_entries(receiver)
                if e["role"] not in received and e["role"] in record]
   return {"record": record, "flags": rt.flag_names(flags), "received": sorted(received), "rederived": rederived,
           "bytes": len(data), "sent": sent, "plain": plain}


def value_text(value: Any) -> str:
   """!A record value as shown (an int, a list, {stat: value}).
   @param value  the value
   @return text
   """
   if isinstance(value, dict):
      return " ".join(f"{k} {v}" for k, v in value.items())
   if isinstance(value, list):
      return " ".join(str(v) for v in value)
   return "" if value is None else str(value)


def derived_lines(rows: list[DerivedRow]) -> list[str]:
   """!The derived preview as the CLI's `role preview` prints it.
   @param rows  derived_rows() result
   @return lines
   """
   out = []
   for r in rows:
      text = f"{r['index']} {r['role']} ({r['state']}): {value_text(r['value'])}"
      if r["rederived"] is not None and r["rederived"] != r["value"]:
         text += f" (rederive() writes {value_text(r['rederived'])})"
      out.append(text)
   return out


def transfer_lines(result: JsonDict) -> list[str]:
   """!A transfer preview as the CLI's `role import` prints it.
   @param result  transfer_preview() result
   @return lines
   """
   out = [f"{result['bytes']} transfer bytes; flags: {', '.join(result['flags']) or 'none'}",
          f"re-derived: {', '.join(result['rederived']) or 'none'}"]
   out += [f"{k} {value_text(v)}" for k, v in result["record"].items()]
   return out
