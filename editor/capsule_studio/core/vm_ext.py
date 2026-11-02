"""![VX] VM extension manifests (D-39, capsule.vm-ext/1): the model behind the Studio's VM extensions view.

A game declares its own script-machine opcodes in extension manifests: each op is an **alias** (data only: a short
fixed sequence of the engine's generic steps with the op's operand layout) or a **native** (a named C++ function in
the game's tier, with the reason no generic step works). Shrinking the natives is how D-39 measures progress. This
module reads the manifests with the engine's own tools/vm_ext.py (core.engine.tool()), so the Studio shows exactly
what the build generates and checks, and adds what a build leaves next to it: the banks' usage records
(capsule.vm-usage/1: how often each op is emitted) and a GBA build's symbol sizes (an `nm -S -C` listing).

Nothing here writes a manifest: they are the game's source files, edited as text and reviewed.
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from . import engine

## The engine sandbox's manifest (simple shapes), the view's sample.
SANDBOX_MANIFEST = Path("apps") / "sandbox_battle_vm" / "data" / "sandbox_vm_ext.json"
## The usage record schema.
USAGE_SCHEMA = "capsule.vm-usage/1"
## Kind filters of the op list: label -> kinds shown.
FILTERS = {"All ops": ("alias", "native"), "Natives": ("native",), "Aliases": ("alias",)}
## Percent of a whole.
PERCENT = 100


class ExtensionError(Exception):
   """!A manifest, usage record or size listing that cannot be read (its message says why)."""


def tool() -> ModuleType:
   """!The engine's tools/vm_ext.py.
   @return the module
   @throws engine.EngineNotFound when no engine checkout is found
   """
   return engine.tool("vm_ext")


def sandbox_manifest() -> Path:
   """!The engine sandbox's manifest, the view's sample.
   @return its path
   @throws engine.EngineNotFound when no engine checkout is found
   """
   return engine.root() / SANDBOX_MANIFEST


@dataclass
class OpRow:
   """!One op as the view lists it."""

   ## Its table (table_key(): "battle", "battle:ai", "anim", ...).
   table: str
   ## Its opcode.
   id: int
   ## Its name.
   name: str
   ## "alias" or "native".
   kind: str
   ## The manifest's name.
   manifest: str
   ## Its owner.
   owner: str
   ## Its tier.
   tier: int
   ## It may wait on controllers or frames.
   waits: bool
   ## Bytes of the command (None: variable length).
   size: int | None
   ## A native's C++ function ("" for an alias).
   symbol: str
   ## A native's reason ("" for an alias).
   reason: str
   ## Its operands as "name: type".
   operands: list[str]
   ## An alias's steps (or a native's candidate), one line each.
   steps: list[str]
   ## A native's alias candidate parity ("" when it has none).
   parity: str
   ## Glitch hook ids.
   glitch: list[str]
   ## Times the banks emit it (None: no usage record for its table).
   uses: int | None = None
   ## The native's bytes on the GBA (None: no size listing, or not found).
   gba_bytes: int | None = None


@dataclass
class TableSummary:
   """!One command table's progress (D-39 measures the natives left)."""

   ## Its key.
   table: str
   ## Ops.
   ops: int
   ## Aliases.
   aliases: int
   ## Natives.
   natives: int
   ## Natives with a proven alias candidate (should become aliases).
   proven: int
   ## Ops no bank emits (None: no usage record).
   unused: int | None

   @property
   def alias_percent(self) -> int:
      """!The aliases' share of the ops.
      @return percent (0 for an empty table)
      """
      return self.aliases * PERCENT // self.ops if self.ops else 0


@dataclass
class Extensions:
   """!Manifests read together, with usage and sizes when given."""

   ## The manifests' files.
   paths: list[Path]
   ## Every op, by table then id.
   rows: list[OpRow] = field(default_factory=list)
   ## The checks' errors (the engine's check()).
   errors: list[str] = field(default_factory=list)
   ## The checks' warnings.
   warnings: list[str] = field(default_factory=list)
   ## Usage counts by table key (empty: none given).
   usage: dict[str, dict[str, int]] = field(default_factory=dict)

   def tables(self) -> list[str]:
      """!The command tables, in the manifests' order.
      @return their keys
      """
      out: list[str] = []
      for r in self.rows:
         if r.table not in out:
            out.append(r.table)
      return out

   def summary(self) -> list[TableSummary]:
      """!Each table's progress.
      @return one summary per table
      """
      out = []
      for t in self.tables():
         rows = [r for r in self.rows if r.table == t]
         aliases = sum(1 for r in rows if r.kind == "alias")
         unused = sum(1 for r in rows if r.uses == 0) if t in self.usage else None
         out.append(TableSummary(t, len(rows), aliases, len(rows) - aliases,
                                 sum(1 for r in rows if r.kind == "native" and r.parity == "proven"), unused))
      return out

   def filtered(self, table: str | None, kinds: Sequence[str], text: str = "") -> list[OpRow]:
      """!The rows a view shows.
      @param table  one table's key, or None for every table
      @param kinds  the kinds shown (FILTERS' values)
      @param text   a name or reason filter (case-insensitive; "" for all)
      @return the rows
      """
      needle = text.lower()
      return [r for r in self.rows if (table is None or r.table == table) and r.kind in kinds and
              (not needle or needle in r.name.lower() or needle in r.reason.lower())]


def _step_text(step: dict[str, Any]) -> str:
   """!One step as a line ("jump_if width 1: compare=cmp, ref=var, value=value, target=target").
   @param step  the manifest's step
   @return the line
   """
   extra = [f"{k} {step[k]}" for k in ("width", "alu", "when") if k in step]
   args = ", ".join(f"{k}={v if isinstance(v, str) else json.dumps(v)}" for k, v in step.get("args", {}).items())
   return f"{step.get('op')}{' ' + ' '.join(extra) if extra else ''}: {args}"


def load(paths: Sequence[Path], usage: Sequence[Path] = (), sizes: Path | None = None,
         sources: Sequence[Path] = ()) -> Extensions:
   """!Reads manifests (with the engine's checks), and the usage records and GBA sizes when given.
   @param paths    the manifests
   @param usage    usage records (capsule.vm-usage/1)
   @param sizes    an `nm -S -C` listing of a GBA build, or None
   @param sources  C++ sources for the implementation checks (default: each manifest's own dispatch.sources)
   @return the extensions
   @throws ExtensionError when a file cannot be read or a manifest is refused
   @throws engine.EngineNotFound when no engine checkout is found
   """
   vm_ext = tool()
   try:
      manifests = vm_ext.load_all([Path(p) for p in paths])
      counts = vm_ext.read_usage([Path(u) for u in usage]) if usage else {}
      symbol_sizes = vm_ext.read_sizes(Path(sizes)) if sizes is not None else {}
      errors, warnings = vm_ext.check(manifests, [Path(s) for s in sources], counts or None)
   except (vm_ext.ManifestError, OSError, KeyError, ValueError) as e:
      raise ExtensionError(str(e)) from None
   out = Extensions([Path(p) for p in paths], errors=list(errors), warnings=list(warnings), usage=counts)
   for m in manifests:
      for ident, op in sorted(m.ops.items()):
         table_counts = counts.get(m.key)
         row = OpRow(m.key, ident, op.name, op.kind, m.name, op.owner, op.tier, op.waits, op.size, op.symbol or "",
                     op.reason, [f"{o.name}: {o.type}" for o in op.operands], [_step_text(s) for s in op.steps],
                     op.parity, list(op.glitch))
         row.uses = table_counts.get(op.name, 0) if table_counts is not None else None
         if op.kind == "native" and symbol_sizes:
            row.gba_bytes = symbol_sizes.get(op.symbol or "")
         out.rows.append(row)
   return out


def report_text(ext: Extensions) -> str:
   """!A plain-text report of the natives (what the view's Copy report gives): table, id, name, owner, GBA bytes,
   reason.
   @param ext  the extensions
   @return the text, one native per line, a summary line per table first
   """
   lines = []
   for s in ext.summary():
      lines.append(f"{s.table}: {s.ops} ops, {s.aliases} aliases ({s.alias_percent}%), {s.natives} natives"
                   + (f", {s.unused} unused" if s.unused is not None else ""))
   for r in ext.rows:
      if r.kind == "native":
         size = f"{r.gba_bytes} B" if r.gba_bytes is not None else "-"
         lines.append(f"{r.table}\t{r.id:#04x}\t{r.name}\t{r.owner}\t{size}\t{r.reason}")
   return "\n".join(lines) + "\n"
