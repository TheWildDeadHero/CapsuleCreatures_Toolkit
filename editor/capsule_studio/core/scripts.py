"""!Editing logic for a game's scripts (B-1, B-2, B-4): the capsule.scripts/1
manifest and its .cscript sources.

The engine's compiler (tools/script_compiler.py) is the one authority on the
language: checks run it on the open buffers, so the editor shows exactly the
errors a build would. This module adds what an editor needs on top: source
files as buffers with dirty state, the manifest's settings, an outline of
declarations, and renames that follow every use.

Qt-free; the script editor panel and the `capsule-studio script` commands use
it.

: the outline also lists the named move routes (movement),
mart lists (mart) and game route steps (step); a map's detail names each
trigger entry with its condition (on_frame, on_warp_into) and script; the
settings include object_base, warn_unused and glitches.

: the lifetimes come from the compiler (lifetimes(): "session" keeps a flag or variable in RAM
only); the manifest's "vm" switches (vm_options(): resume the instruction after a wait on the next frame, random()
modulo n, full-range u8 / u16 variables wrap) are a setting checked by the compiler's vm_flags(); var_wraps() says
which variables wrap under them.
"""
from __future__ import annotations

import json
import types
from pathlib import Path
from typing import Any

from . import engine

## Lifetime names (B-2), as the language spells them, when the engine's compiler does not list them (lifetimes()).
LIFETIMES = ["permanent", "daily", "area", "map"]
## The variable types whose whole range wraps under the "vars": "wrap" switch, with their highest value (the
## engine's script.cpp wraps(): u8 0-255, u16 0-65535).
WRAPPING_TYPES = {"u8": 0xFF, "u16": 0xFFFF}
## The "vm" switch and value that make full-range variables wrap.
VARS_WRAP = ("vars", "wrap")
## Variable types.
TYPES = ["u8", "u16", "u32"]
## Template for a new source file.
NEW_SOURCE = """// {name}: scripts, flags and variables.

flag example_seen;

script example {{
    if !flag(example_seen) {{
        msgbox "Hello!";
        set flag(example_seen);
    }}
    close_msg;
}}
"""
## Template for a source added to a manifest (declares nothing, so it never clashes).
ADDED_SOURCE = """// {name}: scripts, flags and variables.
"""
## Call stack depth of a new manifest (the compiler's default).
NEW_STACK_DEPTH = 20
## Deepest call stack a manifest may ask for (script_compiler.MAX_STACK).
MAX_STACK_DEPTH = 32
## Indent of the manifest JSON as written.
JSON_INDENT = 2
## Tokens back from a "{" or "(" to the keyword of a declaration ("script NAME {", "native NAME (").
KEYWORD_OFFSET = 2
## Tokens from a statement's first word to the battle manifest name it takes ("field_action available NAME").
STATEMENT_NAME_AHEAD = 2
## Declaration kinds of the outline, in its order ([the older studio]: the script ports' movement, mart and step after
## the B-4 ones).
OUTLINE_KINDS = ("script", "flag", "var", "const", "native", "map", "movement", "mart", "step")
## Manifest settings set_setting() changes ([the older studio]: the script ports' object_base, warn_unused, glitches).
SETTING_KEYS = ("game", "games", "stack_depth", "assets", "world", "object_base", "warn_unused", "glitches", "vm")
## The arrow between a map trigger's kind (and condition) and its script.
TRIGGER_ARROW = "->"

## A parsed JSON object (the manifest, an outline item, a syntax node, the compiler's result).
JsonDict = dict[str, Any]
## The engine's script_compiler.Compiler (that module is imported at run time, see compiler()).
ScriptCompiler = Any
## A token of the engine's script_compiler.tokenize() (kind, text, line, col).
Token = Any


class ScriptsError(Exception):
   """!An editing operation was refused; the message says why."""
   pass


def lifetimes() -> list[str]:
   """!The lifetimes a flag or variable may have (the engine's script_compiler.LIFETIMES: the field options adds
   "session").
   @return names, the default first
   """
   try:
      return [str(x) for x in getattr(compiler(), "LIFETIMES", LIFETIMES)]
   except engine.EngineNotFound:
      return list(LIFETIMES)


def vm_options() -> dict[str, list[str]]:
   """!The scripts manifest's "vm" switches (the engine's script_compiler.VM_OPTIONS): switch -> its values, the
   engine's own behaviour first.
   @return {} for an older engine
   """
   try:
      options = getattr(compiler(), "VM_OPTIONS", {})
   except engine.EngineNotFound:
      return {}
   return {str(k): [str(w) for w in sorted(v, key=lambda w: v[w])] for k, v in options.items()}


def var_wraps(type_: str, lo: int, hi: int, vm: dict[str, Any] | None) -> bool:
   """!Whether a variable wraps (the engine's script.cpp wraps()): the "vars": "wrap" switch on, a u8 or u16 of
   its type's whole range; any other saturates.
   @param type_  u8, u16 or u32
   @param lo     its lowest value
   @param hi     its highest value
   @param vm     the manifest's "vm" setting, or None
   @return True when it wraps
   """
   return (vm or {}).get(VARS_WRAP[0]) == VARS_WRAP[1] and type_ in WRAPPING_TYPES and lo == 0 and \
      hi == WRAPPING_TYPES[type_]


def compiler() -> types.ModuleType:
   """!The engine's script compiler module.
   @return module
   """
   return engine.tool("script_compiler")


class Outline:
   """!Declarations found by the last check, with where they are."""

   def __init__(self) -> None:
      """!Creates an empty outline."""
      ## kind -> list of dict(name, file, line, detail), kinds: OUTLINE_KINDS.
      self.items = {k: [] for k in OUTLINE_KINDS}

   def names(self, kind: str) -> list[str]:
      """!Names of one kind, in declaration order.
      @param kind  one of OUTLINE_KINDS
      @return list of names
      """
      return [i["name"] for i in self.items[kind]]

   def find(self, name: str) -> JsonDict | None:
      """!Where a name is declared.
      @param name  any declared name
      @return dict (kind, name, file, line, detail), or None
      """
      for kind, items in self.items.items():
         for i in items:
            if i["name"] == name:
               return dict(i, kind=kind)
      return None


class CheckResult:
   """!Diagnostics, summary and outline of one compile."""

   def __init__(self, comp: ScriptCompiler, texts: dict[str, str] | None = None) -> None:
      """!Builds the result from a script_compiler.Compiler that ran.
      @param comp   the compiler
      @param texts  the sources it compiled, by path (a map's trigger conditions are read from them), or None
      """
      ## All diagnostics (errors and warnings), in order.
      self.diagnostics = list(comp.diags)
      ## Errors only.
      self.errors = [d for d in self.diagnostics if d.severity == "error"]
      ## Warnings only.
      self.warnings = [d for d in self.diagnostics if d.severity == "warning"]
      ## The compiler's result dict when it compiled (bytecode, layout, ...), else None.
      self.result = comp.result if not self.errors else None
      ## Bytes of flags and variables in a save (0 when it did not compile).
      self.save_bytes = comp.save_bytes() if self.result else 0
      ## Declarations (also on errors: whatever parsed).
      self.outline = Outline()
      ## The override sets of the manifest's world, in its order (`override apply|clear NAME`).
      self.override_sets = [str(n) for n in (getattr(comp, "world_field", None) or {}).get("override_sets", [])]
      where = getattr(comp, "where", {})
      # The script ports: movements, marts and game route steps (an older engine has none)
      steps = {n: where.get(n, {}) for n in getattr(comp, "route_steps", [])}
      for kind, table in (("script", comp.scripts), ("flag", comp.flags), ("var", comp.vars),
                          ("const", comp.consts), ("native", comp.natives), ("map", comp.maps),
                          ("movement", getattr(comp, "movements", {})), ("mart", getattr(comp, "marts", {})),
                          ("step", steps)):
         for name, node in table.items():
            detail = _map_detail(node, texts or {}) if kind == "map" else _detail(kind, node)
            if kind == "step":
               detail = f"id {list(steps).index(name)}"
            self.outline.items[kind].append({"name": name, "file": node.get("file", ""),
                                             "line": node.get("line", 0), "detail": detail})
      # Each kind in source order: by file, then line.
      for items in self.outline.items.values():
         items.sort(key=lambda i: (i["file"], i["line"]))

   @property
   def ok(self) -> bool:
      """!Whether it compiles.
      @return True without errors
      """
      return len(self.errors) == 0

   def summary(self) -> str:
      """!One line about the bank.
      @return text
      """
      if len(self.errors) > 0:
         return f"{len(self.errors)} error(s), {len(self.warnings)} warning(s)"
      r = self.result
      return (f"{r['script_count']} scripts, {len(r['flag_names'])} flags, {len(r['vars'])} variables, "
              f"{len(r['code'])} B code, {self.save_bytes} B save" +
              (f", {len(self.warnings)} warning(s)" if self.warnings else ""))


def _load_world_data(sc: types.ModuleType, comp: Any, world: Path) -> None:
   """!what the engine's compile_file() gives the compiler from the manifest's world besides its map names: the
   maps' script uses, the movement modes and the field data (darkness / flight points / escape, doors override
   sets: `override apply NAME` names a set of the world). Each part only when the engine has it.
   @param sc     the engine's script_compiler module
   @param comp   its Compiler, not run yet
   @param world  the world manifest
   @return None
   """
   for attr, loader in (("world_uses", "load_world_uses"), ("vehicle_names", "load_vehicle_names"),
                        ("world_field", "load_world_field")):
      fn = getattr(sc, loader, None)
      if fn is None:
         continue
      try:
         value = fn(world)
      except (OSError, ValueError):
         continue   # the map names' read reports an unreadable world
      except sc.ScriptError as e:
         comp.err(e.message)
         continue
      # load_world_uses() also gives the files it read: the compiler keeps the uses
      setattr(comp, attr, value[0] if attr == "world_uses" else value)


def _detail(kind: str, node: JsonDict) -> str:
   """!A short description of a declaration for the outline.
   @param kind  declaration kind
   @param node  its syntax node
   @return text
   """
   if kind == "flag":
      return node["lifetime"]
   if kind == "var":
      lo, hi = node.get("lo"), node.get("hi")
      rng = f" {lo}..{hi}" if lo is not None else ""
      return f"{node['type']} {node['lifetime']}{rng}"
   if kind == "const":
      return str(node["value"])
   if kind == "native":
      out = f"({', '.join(node['params'])})"
      if node["returns"]:
         out += " -> value"
      if node["waits"]:
         out += " waits"
      return out
   if kind == "map":
      return ", ".join(e["kind"] for e in node["entries"])
   if kind == "movement":
      return f"{len(node.get('steps', []))} steps"
   if kind == "mart":
      return f"{len(node.get('items', []))} items"
   return ""


def _map_detail(node: JsonDict, texts: dict[str, str]) -> str:
   """!A map_scripts table for the outline: each trigger entry as kind [condition] -> script, the condition
   read from its source line (on_frame and on_warp_into entries have one).
   @param node   the map_scripts node
   @param texts  sources by path
   @return text
   """
   lines = texts.get(node.get("file", ""), "").split("\n")
   out = []
   for e in node["entries"]:
      cond = ""
      if e.get("cond") is not None and 0 < e.get("line", 0) <= len(lines):
         # the source between the kind and the arrow (one line per entry, as the language is written)
         src = lines[e["line"] - 1]
         at = src.find(e["kind"])
         end = src.find(TRIGGER_ARROW, at)
         if at >= 0 and end > at:
            cond = " " + src[at + len(e["kind"]):end].strip()
      out.append(f"{e['kind']}{cond} {TRIGGER_ARROW} {e['script']}")
   return ", ".join(out)


class ScriptProject:
   """!A scripts manifest and its sources, as editable buffers."""

   def __init__(self, path: str | Path, manifest: JsonDict, texts: dict[str, str]) -> None:
      """!Use open() or create().
      @param path      manifest path
      @param manifest  parsed manifest
      @param texts     {relative source path: text}
      """
      ## Manifest path.
      self.path = Path(path)
      ## The manifest (JSON object).
      self.manifest = manifest
      ## Source texts by manifest-relative path.
      self.texts = dict(texts)
      ## Texts as last saved, to tell dirty buffers.
      self.saved = dict(texts)
      ## Whether the manifest itself changed.
      self.manifest_dirty = False
      ## Sources listed in the manifest but missing on disk (created on save).
      self.missing = [s for s in manifest.get("sources", []) if s not in texts]
      ## Sources on disk that are not UTF-8 text: shown read-only, never saved.
      self.unreadable = []
      ## The battle data's places the last rename() rewrote ("where" strings, already saved).
      self.followed: list[str] = []

   # Opening and saving.

   @classmethod
   def open(cls, path: str | Path) -> ScriptProject:
      """!Opens a manifest and reads its sources.
      @param path  scripts.json
      @return ScriptProject
      @throws ScriptsError when the manifest is not a scripts manifest
      """
      path = Path(path)
      try:
         manifest = json.loads(path.read_text(encoding="utf-8"))
      except (OSError, ValueError) as e:
         raise ScriptsError(f"cannot read {path.name}: {e}") from e
      if not isinstance(manifest, dict) or manifest.get("schema") != "capsule.scripts/1":
         raise ScriptsError(f"{path.name} is not a scripts manifest (schema capsule.scripts/1)")
      texts = {}
      unreadable = []
      for rel in manifest.get("sources", []):
         p = path.parent / rel
         try:
            texts[rel] = p.read_text(encoding="utf-8")
         except UnicodeDecodeError:
            unreadable.append(rel)   # the check reports it; never overwritten
         except OSError:
            pass
      project = cls(path, manifest, texts)
      project.unreadable = unreadable
      project.missing = [s for s in project.missing if s not in unreadable]
      return project

   @classmethod
   def create(cls, path: str | Path, name: str = "main") -> ScriptProject:
      """!Writes a new manifest with one source file.
      @param path  scripts.json to create (its folder may not exist yet)
      @param name  name of the first source (name.cscript)
      @return ScriptProject
      @throws ScriptsError when the manifest exists already
      """
      path = Path(path)
      if path.exists():
         raise ScriptsError(f"{path} exists already")
      rel = f"{name}.cscript"
      manifest = {"schema": "capsule.scripts/1", "sources": [rel], "stack_depth": NEW_STACK_DEPTH}
      path.parent.mkdir(parents=True, exist_ok=True)
      if not (path.parent / rel).exists():
         (path.parent / rel).write_text(NEW_SOURCE.format(name=name), encoding="utf-8")
      path.write_text(json.dumps(manifest, indent=JSON_INDENT) + "\n", encoding="utf-8")
      return cls.open(path)

   @property
   def sources(self) -> list[str]:
      """!Source paths in manifest order.
      @return list of str
      """
      return list(self.manifest.get("sources", []))

   def dirty_files(self) -> list[str]:
      """!Sources changed since they were saved (or never saved).
      @return list of relative paths
      """
      known = self.sources
      return [s for s in known if self.texts.get(s) != self.saved.get(s)]

   @property
   def dirty(self) -> bool:
      """!Whether anything is unsaved.
      @return True when a source or the manifest changed
      """
      return self.manifest_dirty or bool(self.dirty_files())

   def set_text(self, rel: str, text: str) -> None:
      """!Replaces a source buffer's text (not saved yet).
      @param rel   source path
      @param text  new text
      @return None
      """
      known = self.sources
      if rel not in known:
         raise ScriptsError(f"{rel} is not a source of this manifest")
      if rel in self.unreadable:
         raise ScriptsError(f"{rel} is not UTF-8 text; convert it before editing")
      self.texts[rel] = text

   def save(self, rel: str | None = None) -> None:
      """!Saves one source, or the manifest and every source.
      @param rel  source path, or None for everything
      @return None
      """
      targets = [rel] if rel is not None else self.sources
      # One source is always written; saving everything writes changed and missing sources only.
      for r in targets:
         if r in self.texts and (rel is not None or self.texts.get(r) != self.saved.get(r)
                                 or r in self.missing):
            p = self.path.parent / r
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(self.texts[r], encoding="utf-8")
            self.saved[r] = self.texts[r]
            if r in self.missing:
               self.missing.remove(r)
      if rel is None and self.manifest_dirty:
         self.path.write_text(json.dumps(self.manifest, indent=JSON_INDENT) + "\n", encoding="utf-8")
         self.manifest_dirty = False

   # Manifest settings.

   def setting(self, key: str, default: Any = None) -> Any:
      """!A manifest setting.
      @param key      one of SETTING_KEYS
      @param default  value when absent
      @return the value
      """
      return self.manifest.get(key, default)

   def set_setting(self, key: str, value: Any) -> None:
      """!Changes a manifest setting (None removes it).
      @param key    one of SETTING_KEYS
      @param value  new value
      @throws ScriptsError for an unknown key or a bad value
      @return None
      """
      if key not in SETTING_KEYS:
         raise ScriptsError(f"unknown setting {key!r}")
      # The script ports: the local ID numbering's start, the unused warnings, the glitch switches (the engine's limits)
      top = getattr(compiler(), "MAX_OBJECT_BASE", 0)
      if key == "object_base" and value is not None and (isinstance(value, bool) or not isinstance(value, int)
                                                         or not 0 <= value <= top):
         raise ScriptsError(f"object_base must be 0-{top}")
      if key == "warn_unused" and value is not None and not isinstance(value, bool):
         raise ScriptsError("warn_unused must be true or false")
      if key == "glitches" and value is not None and not (isinstance(value, dict) and all(
            isinstance(k, str) and isinstance(v, bool) for k, v in value.items())):
         raise ScriptsError("glitches map each glitch id to true (on) or false (off)")
      if key == "vm" and value is not None:   # the field options: the compiler's own check of the switches
         sc = compiler()
         if not hasattr(sc, "vm_flags"):
            raise ScriptsError("this engine's scripts have no vm switches")
         try:
            sc.vm_flags(value)
         except sc.ScriptError as e:
            raise ScriptsError(str(e)) from None
         value = dict(value) or None
      if key == "stack_depth" and value is not None and (not isinstance(value, int)
                                                         or not 1 <= value <= MAX_STACK_DEPTH):
         raise ScriptsError(f"stack_depth must be 1-{MAX_STACK_DEPTH}")
      if key == "games" and value is not None and (not isinstance(value, list) or not value):
         raise ScriptsError("games must be a non-empty list of names")
      if value is None:
         self.manifest.pop(key, None)
      else:
         self.manifest[key] = value
      self.manifest_dirty = True

   def add_source(self, rel: str | Path, text: str | None = None) -> None:
      """!Adds a source file to the manifest (created on save if new).
      @param rel   path relative to the manifest, ending in .cscript
      @param text  initial text (default: the file's, or a template)
      @throws ScriptsError when it is listed already or not a .cscript file
      @return None
      """
      rel = Path(rel).as_posix()
      if not rel.endswith(".cscript"):
         raise ScriptsError("script sources end in .cscript")
      known = self.sources
      if rel in known:
         raise ScriptsError(f"{rel} is a source already")
      p = self.path.parent / rel
      if text is None:
         text = p.read_text(encoding="utf-8") if p.exists() else ADDED_SOURCE.format(name=Path(rel).stem)
      self.manifest.setdefault("sources", []).append(rel)
      self.texts[rel] = text
      # A file on disk counts as saved only while the buffer still matches it.
      if p.exists():
         self.saved[rel] = text if p.read_text(encoding="utf-8") == text else None
      else:
         self.missing.append(rel)
      self.manifest_dirty = True

   def remove_source(self, rel: str) -> None:
      """!Removes a source from the manifest (the file stays on disk).
      @param rel  source path
      @return None
      """
      known = self.sources
      if rel not in known:
         raise ScriptsError(f"{rel} is not a source")
      self.manifest["sources"].remove(rel)
      self.texts.pop(rel, None)
      self.saved.pop(rel, None)
      if rel in self.missing:
         self.missing.remove(rel)
      self.manifest_dirty = True

   # Checking.

   def check(self) -> CheckResult:
      """!Compiles the current buffers with the engine's compiler.
      @return CheckResult
      """
      sc = compiler()
      assets = maps = None
      base = self.path.parent
      # This first compiler only carries the error when a named manifest cannot be read.
      comp = sc.Compiler(self.manifest, base, dict(self.texts))
      try:
         if self.manifest.get("assets"):
            assets = sc.load_asset_keys(base / self.manifest["assets"])
         if self.manifest.get("world"):
            maps = sc.load_map_names(base / self.manifest["world"])
      except (OSError, ValueError) as e:
         comp.err(f"cannot read a manifest the scripts manifest names: {e}")
         return CheckResult(comp, self.texts)
      comp = sc.Compiler(self.manifest, base, dict(self.texts), assets, maps)
      if self.manifest.get("world"):
         _load_world_data(sc, comp, base / self.manifest["world"])
      comp.run()
      return CheckResult(comp, self.texts)

   # Editing helpers.

   def declare(self, rel: str, kind: str, name: str, lifetime: str = "permanent", type_: str = "u8",
               lo: int | None = None, hi: int | None = None) -> str:
      """!Appends a flag or variable declaration to a source.
      @param rel       source path
      @param kind      'flag' or 'var'
      @param name      new name
      @param lifetime  one of LIFETIMES
      @param type_     variable type (one of TYPES)
      @param lo        lowest value, or None for the type's
      @param hi        highest value, or None for the type's
      @return the line added
      @throws ScriptsError for a bad name or a name in use
      """
      sc = compiler()
      known = self.sources
      if rel not in known:
         raise ScriptsError(f"{rel} is not a source")
      if not _is_name(name) or name in sc.KEYWORDS:
         raise ScriptsError(f"{name!r} is not a valid name (letters, digits, _; not a keyword)")
      if lifetime not in lifetimes():
         raise ScriptsError(f"lifetime must be one of {', '.join(lifetimes())}")
      if self.check().outline.find(name) is not None:
         raise ScriptsError(f"{name!r} is declared already")
      if kind == "flag":
         line = f"flag {name};" if lifetime == "permanent" else f"flag {name} : {lifetime};"
      elif kind == "var":
         if type_ not in TYPES:
            raise ScriptsError(f"type must be one of {', '.join(TYPES)}")
         rng = f" {lo}..{hi}" if lo is not None and hi is not None else ""
         line = f"var {name} : {type_} {lifetime}{rng};"
      else:
         raise ScriptsError("declare makes flags and variables")
      text = self.texts.get(rel, "")
      if text and not text.endswith("\n"):
         text += "\n"
      self.texts[rel] = text + line + "\n"
      return line

   def rename(self, old: str, new: str) -> int:
      """!Renames a script, flag, variable, constant or native everywhere it
      is declared or used (labels and texts are left alone). The battle
      data the manifest names ("battle") follows a script, flag or variable
      rename at once (core.structure.field_expressions.follow_game_rename():
      saved; the sources are saved with save(); the places are in followed).
      @param old  current name
      @param new  new name
      @return number of places changed
      @throws ScriptsError for a bad or taken name, or an unknown one
      """
      sc = compiler()
      if not _is_name(new) or new in sc.KEYWORDS:
         raise ScriptsError(f"{new!r} is not a valid name")
      outline = self.check().outline
      found = outline.find(old)
      if found is None or found["kind"] == "map":
         raise ScriptsError(f"{old!r} is not a declared script, flag, variable, constant or native")
      if outline.find(new) is not None:
         raise ScriptsError(f"{new!r} is declared already")
      count = 0
      changed = {}
      known = self.sources
      for rel in known:
         text = self.texts.get(rel)
         if text is None:
            continue
         try:
            toks = sc.tokenize(text, rel)
         except sc.ScriptError as e:
            raise ScriptsError(f"fix the syntax error first: {e}") from e
         spans = []
         offsets = _line_offsets(text)
         for i in _uses(toks, old):
            t = toks[i]
            # Token lines and columns count from 1.
            start = offsets[t.line - 1] + t.col - 1
            spans.append((start, start + len(old)))
         if spans:
            # The text between the uses, joined with the new name.
            out = []
            last = 0
            for a, b in spans:
               out.append(text[last:a])
               out.append(new)
               last = b
            out.append(text[last:])
            changed[rel] = "".join(out)
            count += len(spans)
      self.texts.update(changed)
      # The battle data the manifest names follows a script, flag or variable rename (the field actions' and
      # step effects' scripts, flag.NAME / var.NAME in the field actions' requirements), saved at once
      from .structure import field_expressions   # local: core.structure imports this module
      battle_json = field_expressions.battle_file(self.path, self.manifest)
      followed = field_expressions.follow_game_rename(battle_json, found["kind"], old, new)
      self.followed.clear()
      self.followed.extend(followed)
      return count + len(followed)

   def rename_statement_name(self, word: str, kinds: list[str], old: str, new: str,
                             implicit: list[tuple[str, str]] | None = None) -> int:
      """!Renames a name of the battle manifest a statement names (engine F1 / the field actions: `field_effect
      start|active|remaining NAME`, `field_action available NAME`), and the implicit names the script compiler makes
      from it (a field effect's variable and expiry script) where the sources use them. Strings and comments are left
      alone (the engine's tokenizer finds the names).
      @param word      the statement's first word
      @param kinds     the words after it that take the name
      @param old       the current name
      @param new       the new name
      @param implicit  (old implicit name, new implicit name) pairs, or None
      @return number of places changed
      @throws ScriptsError when a source does not tokenize
      """
      sc = compiler()
      count = 0
      known = self.sources   # a local alias (Doxygen 1.12 reads `in self.sources` as a new member)
      for rel in known:
         text = self.texts.get(rel)
         if text is None:
            continue
         try:
            toks = sc.tokenize(text, rel)
         except sc.ScriptError as e:
            raise ScriptsError(f"fix the syntax error first: {e}") from e
         offsets = _line_offsets(text)
         spans = []
         for i, t in enumerate(toks):
            # word KIND NAME: the name is two tokens after the word
            if t.kind == "name" and t.text == word and i + STATEMENT_NAME_AHEAD < len(toks) and \
                  toks[i + 1].text in kinds and toks[i + STATEMENT_NAME_AHEAD].text == old:
               n = toks[i + STATEMENT_NAME_AHEAD]
               start = offsets[n.line - 1] + n.col - 1
               spans.append((start, start + len(old), new))
         for old_name, new_name in implicit or []:
            for i in _uses(toks, old_name):
               t = toks[i]
               start = offsets[t.line - 1] + t.col - 1
               spans.append((start, start + len(old_name), new_name))
         if not spans:
            continue
         spans.sort()
         out = []
         last = 0
         for a, b, repl in spans:
            out.append(text[last:a])
            out.append(repl)
            last = b
         out.append(text[last:])
         self.texts[rel] = "".join(out)
         count += len(spans)
      return count


def follow_rename(manifest: Path | None, word: str, kinds: list[str], old: str, new: str,
                  implicit: list[tuple[str, str]] | None = None) -> list[str]:
   """!Makes a game's scripts follow a rename of a battle manifest name (ScriptProject.rename_statement_name()),
   saving the sources it changed; inside an edit group (core.document.group(): every Document edit), undoing the
   group puts the old name back and saves again, redoing renames again.
   @param manifest  the game's scripts manifest, or None (nothing to follow)
   @param word      the statement's first word
   @param kinds     the words after it that take the name
   @param old       the current name
   @param new       the new name
   @param implicit  (old implicit name, new implicit name) pairs, or None
   @return the places rewritten ("FILE (n)"), [] when none
   """
   if manifest is None or old == new:
      return []
   from .document import current_group   # local: core.document does not import this module

   def apply(a: str, b: str, pairs: list[tuple[str, str]]) -> list[str]:
      """!Renames a to b in every source and saves the ones changed.
      @param a      from
      @param b      to
      @param pairs  implicit name pairs (from, to)
      @return the places
      """
      try:
         project = ScriptProject.open(manifest)
      except (ScriptsError, OSError, ValueError):
         return []
      before = dict(project.texts)
      if project.rename_statement_name(word, kinds, a, b, pairs) == 0:
         return []
      changed = [rel for rel in project.sources if project.texts.get(rel) != before.get(rel)]
      for rel in changed:
         project.save(rel)
      return [f"{rel} ({_count_changes(before[rel], project.texts[rel])})" for rel in changed]
   pairs = list(implicit or [])
   places = apply(old, new, pairs)
   g = current_group()
   if places and g is not None:
      back = [(b, a) for a, b in pairs]
      g.on_undo(lambda: apply(new, old, back))
      g.on_redo(lambda: apply(old, new, pairs))
   return places


def _count_changes(before: str, after: str) -> int:
   """!How many lines a rename changed.
   @param before  the old text
   @param after   the new text
   @return lines that differ
   """
   return sum(1 for a, b in zip(before.split("\n"), after.split("\n")) if a != b)


def _uses(toks: list[Token], name: str) -> list[int]:
   """!Indexes of the tokens that name a declared script, flag, variable,
   constant or native. Skipped: labels and goto targets, build variants in
   `game(...)`, map names after `map_scripts`, and a native declaration's
   parameter names (they are only documentation).
   @param toks  tokens of one source
   @param name  the name
   @return list of token indexes
   """
   out = []
   depth = 0           # brace depth
   body = None         # brace depth a script body opened at, or None outside scripts
   variants = False    # inside game( ... )
   params = False      # inside a native declaration's ( ... )
   for i, t in enumerate(toks):
      prev = toks[i - 1] if i > 0 else None
      nxt = toks[i + 1] if i + 1 < len(toks) else None
      if t.kind == "sym":
         if t.text == "{":
            if body is None and i >= KEYWORD_OFFSET and toks[i - KEYWORD_OFFSET].text == "script":
               body = depth
            depth += 1
         elif t.text == "}":
            depth -= 1
            if body is not None and depth == body:
               body = None
         elif t.text == "(" and prev is not None and prev.text == "game":
            variants = True
         elif t.text == "(" and body is None and i >= KEYWORD_OFFSET and toks[i - KEYWORD_OFFSET].text == "native":
            params = True
         elif t.text == ")":
            variants = params = False
         continue
      if t.kind != "name" or t.text != name or variants or params:
         continue
      if prev is not None and prev.text in ("goto", "map_scripts"):
         continue   # a label use, or a map name
      if nxt is not None and nxt.text == ":" and (prev is None or prev.text in (";", "{", "}")):
         continue   # a label definition
      out.append(i)
   return out


def _is_name(text: str) -> bool:
   """!Whether text is an identifier.
   @param text  candidate
   @return True for letters, digits and _, not starting with a digit
   """
   return bool(text) and (text[0].isalpha() or text[0] == "_") and all(c.isalnum() or c == "_" for c in text) \
       and text.isascii()


def _line_offsets(text: str) -> list[int]:
   """!Offset of the first character of every line.
   @param text  the text
   @return list of offsets, line 1 first
   """
   out = [0]
   for i, c in enumerate(text):
      if c == "\n":
         out.append(i + 1)
   return out
