"""!`capsule-studio --project GAME/reference/project.json ext ...`: everything the Plugin data panel does, from the
command line (D-10 parity): the attach points, the game's connectors and their fields, the records with blocks,
setting and removing a block, the connectors' checks, previews, and exporting and importing with a plugin's file
formats. A change is saved only when it adds no error to the connectors' checks.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from capsule_studio.core import plugin_data
from capsule_studio.core.document import DocumentError

if TYPE_CHECKING:
   import argparse

   from capsule_studio.plugins.registry import ExtensionContext, Registry

## A command's body: callable(parsed arguments) -> exit status, or None for 0.
CommandRun = Callable[["argparse.Namespace"], int | None]
## A command's argument setup: callable(parser), its result unused.
CommandSetup = Callable[["argparse.ArgumentParser"], object]
## Indent of the JSON the commands print.
JSON_INDENT = 2


class Usage(Exception):
   """!Bad arguments; the message says what to give."""
   pass


def _wrap(fn: CommandRun) -> Callable[[argparse.Namespace], int]:
   """!Turns Usage, PluginDataError and DocumentError into messages and exit status 1.
   @param fn  callable(args)
   @return callable(args) -> status
   """
   def run(args: argparse.Namespace) -> int:
      try:
         return fn(args) or 0
      except (Usage, plugin_data.PluginDataError, DocumentError) as e:
         print(f"capsule-studio ext: error: {e}")
         return 1
   return run


def _data(args: argparse.Namespace) -> tuple[plugin_data.PluginData, plugin_data.FileStore]:
   """!The game --project names, on its files.
   @param args  parsed arguments
   @return (PluginData, FileStore)
   """
   if not getattr(args, "project", None):
      raise Usage("give the game with --project GAME/reference/project.json (before 'ext')")
   return plugin_data.for_files(args.project)


def _registry(args: argparse.Namespace) -> Registry:
   """!The registry the command line loaded (the project's plugins' formats and previews).
   @param args  parsed arguments
   @return Registry
   """
   reg = getattr(args, "registry", None)
   if reg is None:
      raise Usage("no plugin registry (run through capsule-studio)")
   return reg


def _value(text: str) -> object:
   """!A --field value: JSON when it parses (numbers, true, null, lists), else the text itself.
   @param text  as given
   @return the value
   """
   try:
      return json.loads(text)
   except ValueError:
      return text


def _errors(data: plugin_data.PluginData) -> set[str]:
   """!The connectors' errors now.
   @param data  PluginData
   @return their texts
   """
   return {p.text() for p in data.check().errors()}


def _save(data: plugin_data.PluginData, store: plugin_data.FileStore, before: set[str]) -> int:
   """!Saves the change unless it added an error to the checks.
   @param data    PluginData
   @param store   its FileStore
   @param before  the errors before the change
   @return exit status
   """
   added = sorted(_errors(data) - before)
   if added:
      print("\n".join(added))
      raise Usage("not saved: the change adds the error(s) above")
   for path in store.save():
      print(f"saved {path}")
   return 0


def cmd_points(args: argparse.Namespace) -> None:
   """!ext points.
   @param args  parsed arguments
   @return None
   """
   for name, where in plugin_data.attach_points().items():
      print(f"{name}: {where}")


def cmd_plugins(args: argparse.Namespace) -> None:
   """!ext plugins: the game's connectors, each point's fields.
   @param args  parsed arguments
   @return None
   """
   data, _store = _data(args)
   plugins = data.plugins()
   if not plugins:
      print("the game has no plugin with a connector (project.json \"plugins\")")
   for p in plugins:
      print(f"{p.plugin_id}: {p.title or p.plugin_id}")
      for point in data.points(p.plugin_id):
         fields = data.schema(p.plugin_id, point).get("fields", {})
         print(f"   {point}: " + ", ".join(f"{k} ({f['type']}{', required' if f.get('required') else ''})"
                                         for k, f in fields.items()))


def cmd_list(args: argparse.Namespace) -> None:
   """!ext list: the records with blocks.
   @param args  parsed arguments
   @return None
   """
   data, _store = _data(args)
   ids = [args.plugin] if args.plugin else [p.plugin_id for p in data.plugins()]
   for pid in ids:
      for point in data.points(pid):
         if args.at and point != args.at:
            continue
         for name in data.records(pid, point):
            print(f"{pid} {point} {name}: {json.dumps(data.get(pid, point, name))}")


def cmd_targets(args: argparse.Namespace) -> None:
   """!ext targets: the records a block can go on.
   @param args  parsed arguments
   @return None
   """
   data, _store = _data(args)
   for t in data.targets(args.point):
      print(f"{t.name}: {t.path}")


def cmd_show(args: argparse.Namespace) -> int:
   """!ext show.
   @param args  parsed arguments
   @return 1 when the record has no block
   """
   data, _store = _data(args)
   block = data.get(args.plugin, args.point, args.name)
   if block is None:
      print(f"{args.point} {args.name} has no {args.plugin} block")
      return 1
   print(json.dumps(data.complete(args.plugin, args.point, block) if args.complete else block, indent=JSON_INDENT))
   return 0


def cmd_set(args: argparse.Namespace) -> int:
   """!ext set: a whole block (--json) and/or fields (--field KEY=VALUE) merged into the block there now.
   @param args  parsed arguments
   @return exit status
   """
   data, store = _data(args)
   if args.json is None and not args.field:
      raise Usage("give --json BLOCK, --field KEY=VALUE, or both")
   before = _errors(data)
   if args.json is not None:
      block = _value(args.json)
      if not isinstance(block, dict):
         raise Usage("--json is a JSON object")
   else:
      block = data.get(args.plugin, args.point, args.name)
      if block is None:
         block = data.new_block(args.plugin, args.point)
   for item in args.field or []:
      key, sep, raw = item.partition("=")
      if not sep or not key:
         raise Usage(f"--field is KEY=VALUE, not {item!r}")
      block[key] = _value(raw)
   problems = data.problems(args.plugin, args.point, block)
   if problems:
      raise Usage("; ".join(problems))
   data.set(args.plugin, args.point, args.name, block)
   return _save(data, store, before)


def cmd_remove(args: argparse.Namespace) -> int:
   """!ext remove.
   @param args  parsed arguments
   @return exit status
   """
   data, store = _data(args)
   if data.get(args.plugin, args.point, args.name) is None:
      raise Usage(f"{args.point} {args.name} has no {args.plugin} block")
   before = _errors(data)
   data.set(args.plugin, args.point, args.name, None)
   return _save(data, store, before)


def cmd_check(args: argparse.Namespace) -> int:
   """!ext check: the connectors' checks (schemas, references, validate hooks).
   @param args  parsed arguments
   @return 1 when there is an error
   """
   data, _store = _data(args)
   result = data.check()
   for p in result.problems:
      print(p.text())
   count = sum(len(r) for r in result.records.values())
   print(f"{len(result.plugins)} connector(s), {count} block(s), {len(result.errors())} error(s)")
   return 1 if result.errors() else 0


def cmd_preview(args: argparse.Namespace) -> int:
   """!ext preview.
   @param args  parsed arguments
   @return exit status
   """
   data, _store = _data(args)
   preview = _registry(args).find("preview", args.preview)
   if preview is None:
      raise Usage(f"no preview {args.preview!r} (ext formats lists the previews too)")
   block = data.get(preview.plugin, args.point, args.name)
   block = data.new_block(preview.plugin, args.point) if block is None else block
   print(preview.render(data, args.point, args.name, data.complete(preview.plugin, args.point, block)))
   return 0


def cmd_formats(args: argparse.Namespace) -> None:
   """!ext formats: the loaded plugins' file formats and previews.
   @param args  parsed arguments
   @return None
   """
   reg = _registry(args)
   for f in reg.formats():
      ways = "/".join(w for w, ok in (("export", f.can_export()), ("import", f.can_import())) if ok)
      print(f"format {f.id}: {f.title} (*{f.suffix}; {ways}; {f.plugin})")
   for p in reg.previews():
      print(f"preview {p.id}: {p.title} ({p.plugin}: {', '.join(p.attach_points) or 'every point'})")
   if not reg.formats() and not reg.previews():
      print("no plugin registers a file format or a preview (load the game's with --project)")


def _format(args: argparse.Namespace) -> object:
   """!The format an export or import names.
   @param args  parsed arguments
   @return registry.FileFormat
   """
   fmt = _registry(args).find("format", args.format)
   if fmt is None:
      raise Usage(f"no file format {args.format!r} (ext formats lists them)")
   return fmt


def cmd_export(args: argparse.Namespace) -> int:
   """!ext export.
   @param args  parsed arguments
   @return exit status
   """
   data, _store = _data(args)
   text = data.export(_format(args))
   Path(args.file).write_text(text, encoding="utf-8")
   print(f"wrote {args.file}")
   return 0


def cmd_import(args: argparse.Namespace) -> int:
   """!ext import.
   @param args  parsed arguments
   @return exit status
   """
   data, store = _data(args)
   fmt = _format(args)
   try:
      text = Path(args.file).read_text(encoding="utf-8")
   except OSError as e:
      raise Usage(f"{args.file}: cannot read ({e.strerror})") from None
   changes = data.import_changes(fmt, text)
   before = _errors(data)
   changed = data.apply(fmt.plugin, changes, f"Import {Path(args.file).name}")
   print(f"{changed} record(s) changed")
   if args.dry_run:
      added = sorted(_errors(data) - before)
      print("\n".join(added) if added else "the checks pass; nothing saved (--dry-run)")
      return 1 if added else 0
   return _save(data, store, before)


def _record_args(p: argparse.ArgumentParser, plugin: bool = True) -> None:
   """!PLUGIN POINT NAME.
   @param p       the parser
   @param plugin  with the plugin argument
   @return None
   """
   if plugin:
      p.add_argument("plugin", help="the plugin's id")
   p.add_argument("point", help="the attach point (ext points)")
   p.add_argument("name", help="the record (ext targets POINT; a cell is MAP@x,y)")


def register(ctx: ExtensionContext) -> None:
   """!Registers the ext commands.
   @param ctx  ExtensionContext
   @return None
   """
   def none(_p: argparse.ArgumentParser) -> None:
      """!No arguments."""

   ctx.add_command("points", "the attach points and where their blocks live", none, _wrap(cmd_points))
   ctx.add_command("plugins", "the game's connectors and each attach point's fields", none, _wrap(cmd_plugins))

   def list_args(p: argparse.ArgumentParser) -> None:
      """!ext list arguments."""
      p.add_argument("--plugin", help="only this plugin's blocks")
      p.add_argument("--at", metavar="POINT", help="only blocks at this attach point")

   ctx.add_command("list", "the records with blocks, and their blocks", list_args, _wrap(cmd_list))
   ctx.add_command("targets", "the records a block can go on at an attach point",
                   lambda p: p.add_argument("point", help="the attach point"), _wrap(cmd_targets))

   def show_args(p: argparse.ArgumentParser) -> None:
      """!ext show arguments."""
      _record_args(p)
      p.add_argument("--complete", action="store_true", help="with the defaults filled in")

   ctx.add_command("show", "a record's block", show_args, _wrap(cmd_show))

   def set_args(p: argparse.ArgumentParser) -> None:
      """!ext set arguments."""
      _record_args(p)
      p.add_argument("--json", metavar="BLOCK", help="the whole block, a JSON object")
      p.add_argument("--field", action="append", metavar="KEY=VALUE",
                     help="one field (a JSON value, or text); may be repeated")

   ctx.add_command("set", "sets a record's block (saved when the checks allow)", set_args, _wrap(cmd_set))
   ctx.add_command("remove", "removes a record's block", _record_args, _wrap(cmd_remove))
   ctx.add_command("check", "the connectors' checks: schemas, references, validate hooks", none, _wrap(cmd_check))

   def preview_args(p: argparse.ArgumentParser) -> None:
      """!ext preview arguments."""
      p.add_argument("preview", help="the preview's id (ext formats)")
      _record_args(p, plugin=False)

   ctx.add_command("preview", "a plugin's preview of a record", preview_args, _wrap(cmd_preview))
   ctx.add_command("formats", "the loaded plugins' file formats and previews", none, _wrap(cmd_formats))

   def export_args(p: argparse.ArgumentParser) -> None:
      """!ext export arguments."""
      p.add_argument("format", help="the format's id (ext formats)")
      p.add_argument("file", help="the file to write")

   ctx.add_command("export", "writes a plugin's blocks in one of its file formats", export_args, _wrap(cmd_export))

   def import_args(p: argparse.ArgumentParser) -> None:
      """!ext import arguments."""
      p.add_argument("format", help="the format's id (ext formats)")
      p.add_argument("file", help="the file to read")
      p.add_argument("--dry-run", action="store_true", help="check the changes, save nothing")

   ctx.add_command("import", "reads a file of one of a plugin's formats into its blocks", import_args,
                   _wrap(cmd_import))
