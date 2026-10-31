"""!The save shapes of a game's script banks (engine C6, tools/save_shape.py): the shape hash of each save sub-bank
(flags and variables per lifetime, the name slots) and the save history the scripts manifest names, whose recorded
shapes let older saves load after flags or variables changed (the engine's remaps).

Record a release's shapes before changing flags or variables: record() adds the build's shapes the history does
not hold yet. A permanent sub-bank of an unrecorded older shape refuses the save; a transient one resets.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import engine
from .document import DocumentError

## A parsed JSON object.
JsonDict = dict[str, Any]


def _tools() -> tuple[Any, Any]:
   """!The engine's script compiler and save_shape modules.
   @return (script_compiler, save_shape)
   """
   return engine.tool("script_compiler"), engine.tool("save_shape")


def _compiled(manifest: str | Path) -> Any:
   """!The scripts manifest compiled by the engine.
   @param manifest  capsule.scripts/1 file
   @return the compiler
   @throws DocumentError when it does not compile
   """
   sc, _ss = _tools()
   comp = sc.compile_file(manifest)
   if comp.errors():
      raise DocumentError(f"{manifest}: the scripts do not compile ({comp.errors()[0].message})")
   return comp


def history_path(manifest: str | Path) -> Path:
   """!The save history file of a scripts manifest ("save_history", else save_history.json beside it).
   @param manifest  capsule.scripts/1 file
   @return the path
   """
   import json
   _sc, ss = _tools()
   data = json.loads(Path(manifest).read_text(encoding="utf-8"))
   return Path(ss.history_path(manifest, data))


def rows(manifest: str | Path) -> list[JsonDict]:
   """!The build's sub-banks and whether the history holds each shape.
   @param manifest  capsule.scripts/1 file
   @return [{"bank", "hash", "bytes", "entries" (count), "recorded"}] in sub-bank order
   @throws DocumentError when the scripts or the history cannot be read
   """
   comp = _compiled(manifest)
   _sc, ss = _tools()
   try:
      known = {(s["bank"], s["hash"]) for s in ss.load_history(history_path(manifest))}
   except ss.ShapeError as e:
      raise DocumentError(str(e)) from None
   return [{"bank": s["bank"], "hash": s["hash"], "bytes": s["bytes"], "entries": len(s["entries"]),
            "recorded": s["hash"] == 0 or (s["bank"], s["hash"]) in known} for s in ss.shapes(comp)]


def remaps(manifest: str | Path) -> list[JsonDict]:
   """!The recorded older shapes and how their entries move (the engine's remaps).
   @param manifest  capsule.scripts/1 file
   @return [{"bank", "from_hash", "kept", "dropped"}]
   """
   comp = _compiled(manifest)
   _sc, ss = _tools()
   out = []
   for m in ss.remaps(comp, comp.save_history):
      dropped = sum(1 for mv in m["moves"] if mv[1] == ss.DROPPED)
      out.append({"bank": m["bank"], "from_hash": m["from_hash"], "kept": len(m["moves"]) - dropped,
                  "dropped": dropped})
   return out


def record(manifest: str | Path) -> int:
   """!Adds the build's shapes the save history does not hold (the file is created when missing).
   @param manifest  capsule.scripts/1 file
   @return shapes added
   """
   comp = _compiled(manifest)
   _sc, ss = _tools()
   try:
      return int(ss.record(comp, history_path(manifest)))
   except ss.ShapeError as e:
      raise DocumentError(str(e)) from None


def unrecorded(manifest: str | Path) -> list[str]:
   """!The build's sub-bank shapes the save history does not hold yet (F1: a release check; field effects add
   implicit permanent variables, so the shape of the permanent sub-bank changes with them).
   @param manifest  capsule.scripts/1 file
   @return "BANK 0xHASH" strings ([]: every shape is recorded)
   """
   return [f"{r['bank']} 0x{r['hash']:08X}" for r in rows(manifest) if not r["recorded"]]


def lines(manifest: str | Path) -> list[str]:
   """!The shapes as text (CLI `script save-shapes`).
   @param manifest  capsule.scripts/1 file
   @return lines
   """
   out = [f"{r['bank']:16} 0x{r['hash']:08X} {r['bytes']} B {r['entries']} entries"
          f"{'' if r['recorded'] else '  (not recorded)'}" for r in rows(manifest)]
   out += [f"recorded {m['bank']} 0x{m['from_hash']:08X}: {m['kept']} kept, {m['dropped']} dropped"
           for m in remaps(manifest)]
   return out
