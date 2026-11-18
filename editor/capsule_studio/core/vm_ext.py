"""![VX] VM extension manifests (D-39, capsule.vm-ext/1): the model behind the Studio's VM extensions view.

A game declares its own script-machine opcodes in extension manifests: each op is an **alias** (data only: a short
fixed sequence of the engine's generic steps with the op's operand layout) or a **native** (a named C++ function in
the game's tier, with the reason no generic step works). Shrinking the natives is how D-39 measures progress. This
module reads the manifests with the engine's own tools/vm_ext.py (core.engine.tool()), so the Studio shows exactly
what the build generates and checks, and adds what a build leaves next to it: the banks' usage records
(capsule.vm-usage/1: how often each op is emitted) and a GBA build's symbol sizes (an `nm -S -C` listing).

D-36 package 2 step D adds the field script VM: its generic ops (the engine's src/script/script_vm.json) and a
game's natives table (vm script, table native, written by the game's import), each native with whether the game
implements it, its milestone and its owner's code size; the natives are summarised by class (their reasons' kinds).

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
## Step D: the field script VM's ops in the engine.
SCRIPT_VM_MANIFEST = Path("src") / "script" / "script_vm.json"
## Step D: the engine's script natives sample (simple shapes) and its scripts usage record.
SCRIPT_SAMPLE = Path("tests") / "data" / "vm_ext" / "script_natives_vm_ext.json"
## The sample's usage record.
SCRIPT_SAMPLE_USAGE = Path("tests") / "data" / "vm_ext" / "script_usage.json"
## Step D: a game's natives manifest (its import's world/scripts/) and its scripts usage record (its build's).
GAME_NATIVES_FILE, GAME_USAGE_FILE = "natives_vm_ext.json", "scripts_usage.json"
## The usage record schema.
USAGE_SCHEMA = "capsule.vm-usage/1"
## Kind filters of the op list: label -> kinds shown.
FILTERS = {"All ops": ("generic", "alias", "native"), "Natives": ("native",), "Aliases": ("alias",),
           "Generic ops": ("generic",)}
## Step D: a script native's class, by how its reason starts (the import's natives_manifest.reason()): prefix ->
## label; any other reason is OTHER_CLASS.
NATIVE_CLASSES = (("game-specific", "Game-specific rules"), ("implemented natively", "Implemented, not converted"),
                  ("waits for", "Waiting for a feature"), ("stand-in", "Stand-ins"),
                  ("not implemented", "Not implemented"), ("unclassified", "Unclassified"))
## The class of another reason.
OTHER_CLASS = "Other"
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
   ## Step D: a script native the game runs (None: not a script native).
   implemented: bool | None = None
   ## Step D: a script native's milestone ("" when not given).
   milestone: str = ""
   ## Step D: a script native's owner's code on the GBA (None: no size listing, or no namespace named).
   owner_bytes: int | None = None


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
   ## Step D: the VM's own generic ops (the field script VM's).
   generic: int = 0

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
         generic = sum(1 for r in rows if r.kind == "generic")
         unused = sum(1 for r in rows if r.uses == 0) if t in self.usage else None
         out.append(TableSummary(t, len(rows), aliases, len(rows) - aliases - generic,
                                 sum(1 for r in rows if r.kind == "native" and r.parity == "proven"), unused,
                                 generic))
      return out

   def native_classes(self) -> list[tuple[str, int, int]]:
      """!Step D: the script natives by class (their reasons' kinds; "Not implemented" split by milestone).
      @return (label, natives, uses) in NATIVE_CLASSES' order, then the milestones in order
      """
      counts: dict[str, list[int]] = {}
      for r in self.rows:
         if r.kind != "native" or r.implemented is None:
            continue
         label = native_class(r.reason)
         if label == dict(NATIVE_CLASSES)["not implemented"] and r.milestone:
            label = f"{label} ({r.milestone})"
         c = counts.setdefault(label, [0, 0])
         c[0] += 1
         c[1] += r.uses or 0
      order = [label for _p, label in NATIVE_CLASSES] + [OTHER_CLASS]
      return sorted(((k, v[0], v[1]) for k, v in counts.items()),
                    key=lambda kv: (order.index(kv[0].split(" (")[0]), kv[0]))

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


def native_class(reason: str) -> str:
   """!Step D: a script native's class from its reason.
   @param reason  the reason
   @return a NATIVE_CLASSES label, or OTHER_CLASS
   """
   return next((label for prefix, label in NATIVE_CLASSES if reason.startswith(prefix)), OTHER_CLASS)


def script_sample() -> tuple[list[Path], list[Path]]:
   """!Step D: the engine's script VM with its natives sample (simple shapes) and the sample's usage record.
   @return (manifests, usage records)
   @throws engine.EngineNotFound when no engine checkout is found
   """
   root = engine.root()
   return [root / SCRIPT_VM_MANIFEST, root / SCRIPT_SAMPLE], [root / SCRIPT_SAMPLE_USAGE]


def game_files(folders: Sequence[Path]) -> tuple[list[Path], list[Path]]:
   """!Step D: a game's script VM files: the engine's script VM, the game's natives manifest and its scripts usage
   record, found under the folders given (its import's content, its build folder).
   @param folders  where to look (each searched with its subfolders)
   @return (manifests, usage records); the manifests hold only the engine's script VM when no natives are found
   @throws engine.EngineNotFound when no engine checkout is found
   """
   natives: list[Path] = []
   usage: list[Path] = []
   for folder in folders:
      natives += sorted(Path(folder).rglob(GAME_NATIVES_FILE))[:1]
      usage += sorted(Path(folder).rglob(GAME_USAGE_FILE))[:1]
   return [engine.root() / SCRIPT_VM_MANIFEST] + natives[:1], usage[:1]


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
      # step D: a script native's owner's code (an engine without it has no script natives either)
      namespaces = vm_ext.read_namespace_sizes(Path(sizes)) if sizes is not None and hasattr(
         vm_ext, "read_namespace_sizes") else {}
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
         if hasattr(vm_ext, "is_script_natives") and vm_ext.is_script_natives(m):
            row.gba_bytes = None   # a case inside its package: its owner's bytes instead
            row.implemented, row.milestone = op.implemented, str(op.raw.get("milestone") or "")
            if row.uses is None and isinstance(op.raw.get("uses"), int):
               row.uses = op.raw["uses"]   # the manifest's count when no usage record is given
            row.owner_bytes = vm_ext.owner_bytes(m, op.owner, namespaces) if namespaces else None
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
      lines.append(f"{s.table}: {s.ops} ops, " + (f"{s.generic} generic, " if s.generic else "")
                   + f"{s.aliases} aliases ({s.alias_percent}%), {s.natives} natives"
                   + (f", {s.unused} unused" if s.unused is not None else ""))
   for label, natives, uses in ext.native_classes():
      lines.append(f"{label}: {natives} natives, {uses} uses")
   for r in ext.rows:
      if r.kind == "native":
         measured = r.gba_bytes if r.gba_bytes is not None else r.owner_bytes
         size = f"{measured} B" if measured is not None else "-"
         lines.append(f"{r.table}\t{r.id:#04x}\t{r.name}\t{r.owner}\t{size}\t{r.reason}")
   return "\n".join(lines) + "\n"
