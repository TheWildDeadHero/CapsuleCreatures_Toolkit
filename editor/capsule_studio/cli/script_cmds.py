"""!`capsule-studio script ...`: scripts, flags and variables (B-1, B-2, B-4),
the same operations as the script editor, and the manifest's field
placeholders and terms (core.placeholders):

    script placeholders MANIFEST                       list them, the terms and the markup state
    script placeholder MANIFEST add NAME KIND VALUE [--form F] [--slot N]   KIND name | var | term | record
    script placeholder MANIFEST set NAME KIND VALUE [--form F] [--slot N]
    script placeholder MANIFEST remove NAME | rename OLD NEW | move NAME up|down | markup on|off
    script term MANIFEST set CONCEPT WORD [--plural WORDS] | remove CONCEPT
    script save-shapes MANIFEST [--record]            the save sub-banks' shapes and the save history
    script save-shapes MANIFEST --check               exit 1 when the history lacks one of the build's shapes (F1)

Placeholder changes are checked with the engine's script compiler and saved
only when the scripts still compile.

: `script list` also lists movements, marts and route steps;
`script settings` sets object_base, warn_unused and glitch switches;
`script words [--at TEXT]` lists the language's words (core.script_words)
or the completions at the end of a text.

: `script settings --vm SWITCH VALUE` sets a script VM switch
(resume same_frame|next_frame, random scaled|modulo, vars saturate|wrap; the
engine's own value removes it); `script declare --lifetime session`."""
from __future__ import annotations

import argparse

import json
from typing import Any

from ..core import placeholders, save_shapes, script_words, scripts
from ..core.document import DocumentError
from .main import CommandError

## `move` directions and their deltas.
MOVES = {"up": -1, "down": 1}
## `markup` words.
SWITCH = {"on": True, "off": False}
## Values of a --glitch option (the id, on or off).
GLITCH_ARGS = 2
## Values of a --vm option (the switch, its value).
VM_ARGS = 2


def register(sub: argparse._SubParsersAction) -> None:
   """!Adds the command group.
   @param sub  argparse subparsers
   @return None
   """
   p = sub.add_parser("script", help="scripts, flags and variables (.cscript sources)")
   s = p.add_subparsers(dest="script_command", metavar="ACTION")
   s.required = True
   q = s.add_parser("new", help="create a scripts manifest with one source")
   q.add_argument("manifest", help="scripts.json to create")
   q.add_argument("--source", default="main", help="first source's name (default main)")
   q.set_defaults(run=cmd_new)
   q = s.add_parser("check", help="compile with the engine's compiler and report")
   q.add_argument("manifest")
   q.add_argument("--warnings", action="store_true", help="fail on warnings too")
   q.set_defaults(run=cmd_check)
   q = s.add_parser("list", help="list declarations")
   q.add_argument("manifest")
   q.add_argument("--kind", choices=list(scripts.OUTLINE_KINDS), help="only this kind")
   q.set_defaults(run=cmd_list)
   q = s.add_parser("declare", help="add a flag or variable to a source")
   q.add_argument("manifest")
   q.add_argument("kind", choices=["flag", "var"])
   q.add_argument("name")
   q.add_argument("--source", help="source to add it to (default: the first)")
   q.add_argument("--lifetime", default="permanent", choices=scripts.lifetimes())
   q.add_argument("--type", default="u8", choices=scripts.TYPES, help="variable type")
   q.add_argument("--range", help="variable range, e.g. 0..99")
   q.set_defaults(run=cmd_declare)
   q = s.add_parser("rename", help="rename a script, flag, variable, constant or native everywhere")
   q.add_argument("manifest")
   q.add_argument("old")
   q.add_argument("new")
   q.set_defaults(run=cmd_rename)
   q = s.add_parser("add-source", help="add a .cscript file to the manifest (created when new)")
   q.add_argument("manifest")
   q.add_argument("source", help="path relative to the manifest")
   q.set_defaults(run=cmd_add_source)
   q = s.add_parser("remove-source", help="remove a source from the manifest (the file stays)")
   q.add_argument("manifest")
   q.add_argument("source")
   q.set_defaults(run=cmd_remove_source)
   q = s.add_parser("settings", help="show or change the manifest's settings")
   q.add_argument("manifest")
   q.add_argument("--game", help="build variant for when game(...)")
   q.add_argument("--games", help="comma-separated variants")
   q.add_argument("--stack-depth", type=int, help="VM call depth, 1-32")
   q.add_argument("--assets", help="asset manifest checked for text: references ('' removes)")
   q.add_argument("--world", help="world manifest checked for map names ('' removes)")
   q.add_argument("--object-base", type=int, help="the first local ID of the game's object numbering")
   q.add_argument("--warn-unused", choices=list(SWITCH), help="warn about unused flags and variables")
   q.add_argument("--glitch", nargs=GLITCH_ARGS, action="append", metavar=("ID", "on|off"),
                  help="a glitch variant's switch (repeat for several)")
   q.add_argument("--vm", nargs=VM_ARGS, action="append", metavar=("SWITCH", "VALUE"),
                  help="a script VM switch (resume, random, vars; repeat for several)")
   q.set_defaults(run=cmd_settings)
   q = s.add_parser("words", help="the language's words (from the engine's compilers), or the completions at the "
                                  "end of --at TEXT")
   q.add_argument("--at", help="the source up to the cursor (\\n for a newline)")
   q.add_argument("--manifest", help="a scripts manifest whose declarations complete too")
   q.set_defaults(run=cmd_words)
   _register_placeholders(s)


def _register_placeholders(s: argparse._SubParsersAction) -> None:
   """!Adds `placeholders`, `placeholder ...` and `term ...`.
   @param s  the script group's subparsers
   @return None
   """
   q = s.add_parser("placeholders", help="the field placeholders, terms and markup state")
   q.add_argument("manifest")
   q.set_defaults(run=cmd_placeholders)
   q = s.add_parser("placeholder", help="field placeholders: add | set | remove | rename | move | markup")
   q.add_argument("manifest")
   a = q.add_subparsers(dest="placeholder_command", metavar="ACTION")
   a.required = True
   for word, run in (("add", cmd_placeholder_add), ("set", cmd_placeholder_add)):
      r = a.add_parser(word, help=f"{word} a binding: KIND name (slot length) | var | term | record")
      r.add_argument("name")
      r.add_argument("kind")
      r.add_argument("value")
      r.add_argument("--form", help="a term binding's form (one / many)")
      r.add_argument("--slot", type=int, help="a record binding's party slot")
      r.set_defaults(run=run, change=word)
   r = a.add_parser("remove", help="remove a placeholder no text uses")
   r.add_argument("name")
   r.set_defaults(run=cmd_placeholder_remove)
   r = a.add_parser("rename", help="rename a placeholder; {old} in the texts follows")
   r.add_argument("old")
   r.add_argument("new")
   r.set_defaults(run=cmd_placeholder_rename)
   r = a.add_parser("move", help="move a placeholder (its index)")
   r.add_argument("name")
   r.add_argument("direction", choices=list(MOVES))
   r.set_defaults(run=cmd_placeholder_move)
   r = a.add_parser("markup", help="field texts as markup (on) or plain (off: no placeholders)")
   r.add_argument("state", choices=list(SWITCH))
   r.set_defaults(run=cmd_placeholder_markup)
   q = s.add_parser("save-shapes", help="the save sub-banks' shapes and the save history (--record adds them)")
   q.add_argument("manifest")
   q.add_argument("--record", action="store_true", help="add the build's shapes the history lacks")
   q.add_argument("--check", action="store_true", help="exit 1 when the history lacks one of the build's shapes")
   q.set_defaults(run=cmd_save_shapes)
   q = s.add_parser("term", help="terms: set | remove")
   q.add_argument("manifest")
   a = q.add_subparsers(dest="term_command", metavar="ACTION")
   a.required = True
   r = a.add_parser("set", help="set a concept's word (and plural)")
   r.add_argument("concept")
   r.add_argument("word")
   r.add_argument("--plural")
   r.set_defaults(run=cmd_term_set)
   r = a.add_parser("remove", help="remove a term nothing uses")
   r.add_argument("concept")
   r.set_defaults(run=cmd_term_remove)


def _open(path: str) -> scripts.ScriptProject:
   """!Opens a scripts manifest.
   @param path  scripts.json
   @return ScriptProject
   """
   try:
      return scripts.ScriptProject.open(path)
   except scripts.ScriptsError as e:
      raise CommandError(str(e)) from e


def _report(project: scripts.ScriptProject, result: scripts.CheckResult) -> None:
   """!Prints diagnostics with paths relative to the current folder.
   @param project  ScriptProject
   @param result   CheckResult
   @return None
   """
   for d in result.diagnostics:
      where = str(project.path.parent / d.file) if d.file else str(project.path)
      if d.line:
         where += f":{d.line}:{d.col}"
      print(f"{where}: {d.severity}: {d.message}")


def cmd_new(args: argparse.Namespace) -> None:
   """!script new.
   @param args  parsed arguments
   @return None
   """
   try:
      p = scripts.ScriptProject.create(args.manifest, args.source)
   except scripts.ScriptsError as e:
      raise CommandError(str(e)) from e
   print(f"created {p.path} with {p.sources[0]}")


def cmd_check(args: argparse.Namespace) -> int:
   """!script check.
   @param args  parsed arguments
   @return exit status
   """
   p = _open(args.manifest)
   r = p.check()
   _report(p, r)
   print(f"{p.path}: {r.summary()}")
   if not r.ok or (args.warnings and r.warnings):
      return 1
   return 0


def cmd_list(args: argparse.Namespace) -> None:
   """!script list.
   @param args  parsed arguments
   @return None
   """
   p = _open(args.manifest)
   r = p.check()
   kinds = [args.kind] if args.kind else list(scripts.OUTLINE_KINDS)
   for kind in kinds:
      for item in r.outline.items[kind]:
         detail = f"  {item['detail']}" if item["detail"] else ""
         print(f"{kind:7} {item['name']}{detail}  ({item['file']}:{item['line']})")


def cmd_declare(args: argparse.Namespace) -> None:
   """!script declare.
   @param args  parsed arguments
   @return None
   """
   p = _open(args.manifest)
   rel = args.source or (p.sources[0] if p.sources else None)
   if rel is None:
      raise CommandError("the manifest has no sources; add one with add-source")
   lo = hi = None
   if args.range:
      try:
         a, b = args.range.split("..")
         lo, hi = int(a), int(b)
      except ValueError:
         raise CommandError("range must look like 0..99") from None
   try:
      line = p.declare(rel, args.kind, args.name, args.lifetime, args.type, lo, hi)
   except scripts.ScriptsError as e:
      raise CommandError(str(e)) from e
   p.save()
   print(f"{rel}: {line}")


def cmd_rename(args: argparse.Namespace) -> None:
   """!script rename.
   @param args  parsed arguments
   @return None
   """
   p = _open(args.manifest)
   try:
      n = p.rename(args.old, args.new)
   except scripts.ScriptsError as e:
      raise CommandError(str(e)) from e
   p.save()
   print(f"renamed {args.old} to {args.new} in {n} place(s)")


def cmd_add_source(args: argparse.Namespace) -> None:
   """!script add-source.
   @param args  parsed arguments
   @return None
   """
   p = _open(args.manifest)
   try:
      p.add_source(args.source)
   except scripts.ScriptsError as e:
      raise CommandError(str(e)) from e
   p.save()
   print(f"added {args.source}")


def cmd_remove_source(args: argparse.Namespace) -> None:
   """!script remove-source.
   @param args  parsed arguments
   @return None
   """
   p = _open(args.manifest)
   try:
      p.remove_source(args.source)
   except scripts.ScriptsError as e:
      raise CommandError(str(e)) from e
   p.save()
   print(f"removed {args.source} (the file is kept)")


def cmd_settings(args: argparse.Namespace) -> None:
   """!script settings.
   @param args  parsed arguments
   @return None
   """
   p = _open(args.manifest)
   try:
      if args.game is not None:
         p.set_setting("game", args.game or None)
      if args.games is not None:
         p.set_setting("games", [g.strip() for g in args.games.split(",") if g.strip()] or None)
      if args.stack_depth is not None:
         p.set_setting("stack_depth", args.stack_depth)
      if args.assets is not None:
         p.set_setting("assets", args.assets or None)
      if args.world is not None:
         p.set_setting("world", args.world or None)
      if args.object_base is not None:
         p.set_setting("object_base", args.object_base or None)
      if args.warn_unused is not None:
         p.set_setting("warn_unused", None if SWITCH[args.warn_unused] else False)
      for gid, state in args.glitch or []:
         if state not in SWITCH:
            raise CommandError(f"--glitch {gid}: on or off, not {state!r}")
         p.set_setting("glitches", {**(p.setting("glitches") or {}), gid: SWITCH[state]})
      options = scripts.vm_options()
      for switch, value in args.vm or []:   # the engine's own value (the first) leaves the switch out
         vm = dict(p.setting("vm") or {})
         if switch in options and options[switch] and value == options[switch][0]:
            vm.pop(switch, None)
         else:
            vm[switch] = value
         p.set_setting("vm", vm or None)
   except scripts.ScriptsError as e:
      raise CommandError(str(e)) from e
   if p.manifest_dirty:
      p.save()
   for key in scripts.SETTING_KEYS:
      value = p.setting(key)
      if isinstance(value, dict):
         value = ", ".join(f"{k} {v}" if isinstance(v, str) else f"{k} {'on' if v else 'off'}"
                           for k, v in value.items())
      if value is not None:
         print(f"{key}: {', '.join(value) if isinstance(value, list) else value}")


def cmd_words(args: argparse.Namespace) -> None:
   """!script words.
   @param args  parsed arguments
   @return None
   """
   if args.at is not None:
      names = {}
      if args.manifest:
         names = script_words.check_names(_open(args.manifest).check())   # + the world's override sets
      print(" ".join(script_words.completions(args.at.replace("\\n", "\n"), names)))
      return
   print("declarations: " + " ".join(script_words.declaration_words()))
   print("statements: " + " ".join(script_words.statement_words()))
   for word, kinds in script_words.statement_kinds().items():
      print(f"  {word}: {' '.join(kinds)}")
   print("map triggers: " + " ".join(script_words.trigger_kinds()) + "  (with a condition: "
         + " ".join(script_words.condition_kinds()) + ")")
   steps = script_words.route_steps()
   print("route steps: " + " ".join(f"{w}[{'|'.join(a)}]" if a else w for w, a in steps.steps.items()))
   for word, template in script_words.STATEMENT_TEMPLATES.items():
      print(f"  template {word}: {template}")


# -- placeholders and terms --------------------------------------------------------------------------------------------

def _placeholder_edit(args: argparse.Namespace, label: str, fn: Any) -> int:
   """!One placeholder edit, saved when the scripts still compile.
   @param args   parsed arguments (manifest)
   @param label  undo label
   @param fn     callable(project)
   @return 0, or 1 when the scripts do not compile
   """
   p = _open(args.manifest)
   try:
      with placeholders.edit(p, label):
         fn(p)
   except DocumentError as e:
      raise CommandError(str(e)) from e
   result = p.check()
   if not result.ok:
      _report(p, result)
      print("not saved: the scripts do not compile")
      return 1
   p.save()
   return 0


def cmd_placeholders(args: argparse.Namespace) -> None:
   """!script placeholders.
   @param args  parsed arguments
   @return None
   """
   for line in placeholders.lines(_open(args.manifest)):
      print(line)


def _bound_value(kind: str, text: str) -> Any:
   """!A binding's value from the command line (a name slot's length is a number).
   @param kind  binding kind
   @param text  argument
   @return value
   """
   if kind == "name":
      try:
         return json.loads(text)
      except json.JSONDecodeError:
         return text
   return text


def cmd_placeholder_add(args: argparse.Namespace) -> int:
   """!script placeholder add / set.
   @param args  parsed arguments
   @return status
   """
   extra = {"form": args.form, "slot": args.slot}
   extra = {k: v for k, v in extra.items() if v is not None}
   value = _bound_value(args.kind, args.value)
   fn = placeholders.add_placeholder if args.change == "add" else placeholders.set_placeholder
   return _placeholder_edit(args, "Placeholder", lambda p: fn(p, args.name, args.kind, value, extra))


def cmd_placeholder_remove(args: argparse.Namespace) -> int:
   """!script placeholder remove.
   @param args  parsed arguments
   @return status
   """
   return _placeholder_edit(args, "Remove placeholder", lambda p: placeholders.remove_placeholder(p, args.name))


def cmd_placeholder_rename(args: argparse.Namespace) -> int:
   """!script placeholder rename.
   @param args  parsed arguments
   @return status
   """
   return _placeholder_edit(args, "Rename placeholder",
                            lambda p: print(f"{placeholders.rename_placeholder(p, args.old, args.new)} text(s) "
                                            "changed"))


def cmd_placeholder_move(args: argparse.Namespace) -> int:
   """!script placeholder move.
   @param args  parsed arguments
   @return status
   """
   return _placeholder_edit(args, "Move placeholder",
                            lambda p: placeholders.move_placeholder(p, args.name, MOVES[args.direction]))


def cmd_placeholder_markup(args: argparse.Namespace) -> int:
   """!script placeholder markup.
   @param args  parsed arguments
   @return status
   """
   return _placeholder_edit(args, "Markup", lambda p: placeholders.set_markup(p, SWITCH[args.state]))


def cmd_term_set(args: argparse.Namespace) -> int:
   """!script term set.
   @param args  parsed arguments
   @return status
   """
   return _placeholder_edit(args, "Term", lambda p: placeholders.set_term(p, args.concept, args.word, args.plural))


def cmd_term_remove(args: argparse.Namespace) -> int:
   """!script term remove.
   @param args  parsed arguments
   @return status
   """
   return _placeholder_edit(args, "Remove term", lambda p: placeholders.remove_term(p, args.concept))


def cmd_save_shapes(args: argparse.Namespace) -> int:
   """!Prints the save shapes, records them or checks that the history holds them (F1).
   @param args  parsed arguments
   @return 0, or 1 when --check finds a shape the history lacks
   @throws CommandError when the scripts or the history cannot be read
   """
   try:
      if args.check:
         missing = save_shapes.unrecorded(args.manifest)
         for shape in missing:
            print(f"not recorded: {shape}")
         print("every shape is recorded" if not missing else f"{len(missing)} shapes to record (--record)")
         return 1 if missing else 0
      if args.record:
         print(f"{save_shapes.history_path(args.manifest)}: {save_shapes.record(args.manifest)} shapes added")
         return 0
      for line in save_shapes.lines(args.manifest):
         print(line)
   except (DocumentError, OSError, ValueError) as e:
      raise CommandError(str(e)) from None
   return 0
