"""!`capsule-studio designer ...`: the manifest designer on the command line (D-43 §6), every edit the canvas makes,
through the same core.designer.session.DesignSession. The system is found from the manifest's schema (or named
with --system); each edit saves the file.

    designer systems [--all]                       the systems and what they edit (--all: dev-only ones too)
    designer new FILE --system ID                  a new manifest of a system
    designer show FILE [--json]                    elements, links, live values and problems
    designer check FILE                            the problems; exit status 1 on errors
    designer add FILE KIND --at X,Y [--set F=V]... [--id ID] [--frame ID]
    designer add-wired FILE KIND --at X,Y --from ELEMENT.PORT [--port NAME]
    designer kinds FILE [--from ELEMENT.PORT]      the palette (or the kinds a wire from a port can end on)
    designer remove FILE ID...                     elements (frames with what they hold) or links
    designer move FILE ID... (--by DX,DY | --to X,Y)
    designer resize FILE ID --size W,H
    designer set FILE ID FIELD=VALUE...
    designer connect FILE FROM TO [--label TEXT]   FROM / TO: ELEMENT.PORT (a wire) or ELEMENT (a connector)
    designer disconnect FILE LINK...
    designer label FILE LINK TEXT
    designer frame FILE ID... (--into FRAME | --out)
    designer duplicate FILE ID... [--offset DX,DY]
    designer align FILE EDGE ID...                 EDGE: left centre right top middle bottom (the first id stays)
    designer distribute FILE AXIS ID...            AXIS: horizontal vertical
    designer same-size FILE WHICH ID...            WHICH: width height both (the first id's)
    designer front FILE ID... / designer back FILE ID...
    designer layout FILE                           tidy up: the system's nodes in ranks
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Callable

from ..core.designer import checks, ops, registry
from ..core.designer.model import ModelError, Endpoint, Point
from ..core.designer.session import DesignSession
from .main import CommandError

## The indent of --json.
JSON_INDENT = 1
## Exit status of `designer check` when there are errors.
ERROR_STATUS = 1
## Default offset of `designer duplicate`.
DUPLICATE_OFFSET = (40, 40)
## Separator of a FIELD=VALUE argument.
ASSIGN = "="


def _pair(text: str) -> Point:
   """!Two whole numbers from "X,Y".
   @param text  the argument
   @return the pair
   @throws argparse.ArgumentTypeError when it is not one
   """
   parts = text.split(",")
   try:
      x, y = (int(p) for p in parts)
   except ValueError:
      raise argparse.ArgumentTypeError(f"two whole numbers like 120,40 are needed, not {text!r}") from None
   return (x, y)


def _assignments(items: list[str]) -> dict[str, str]:
   """!FIELD=VALUE arguments.
   @param items  the arguments
   @return field -> value (text; each field converts it)
   @throws CommandError when one has no "="
   """
   out = {}
   for item in items:
      name, sep, value = item.partition(ASSIGN)
      if not sep or not name:
         raise CommandError(f"{item!r}: write FIELD=VALUE")
      out[name] = value
   return out


def _session(args: argparse.Namespace) -> DesignSession:
   """!The session of the FILE argument.
   @param args  parsed arguments
   @return the session
   """
   return DesignSession.open(args.file, args.system)


def _edit(change: Callable[[DesignSession, argparse.Namespace], object]) -> Callable[[argparse.Namespace], int]:
   """!A command that edits the file and saves it.
   @param change  makes the edit on the session
   @return the command function
   """
   def run(args: argparse.Namespace) -> int:
      """!Opens, edits, saves.
      @param args  parsed arguments
      @return 0
      """
      session = _session(args)
      try:
         result = change(session, args)
      except ModelError as e:
         raise CommandError(str(e)) from None
      session.save()
      if isinstance(result, dict) and result:
         for old, new in result.items():
            print(f"{old} -> {new}")
      elif result is not None and hasattr(result, "element_id"):
         print(result.element_id)
      elif result is not None and hasattr(result, "link_id"):
         print(result.link_id)
      label = session.doc.undo_label()
      if label:
         print(f"{label} (saved {args.file})")
      return 0
   return run


def register(sub: argparse._SubParsersAction) -> None:
   """!Adds the command group.
   @param sub  argparse subparsers
   @return None
   """
   p = sub.add_parser("designer", help="the manifest designer: diagrams of a system's manifest (D-43)")
   a = p.add_subparsers(dest="designer_command", metavar="ACTION")
   a.required = True

   def action(name: str, help_text: str, run: Callable[[argparse.Namespace], int],
              file: bool = True) -> argparse.ArgumentParser:
      """!One action.
      @param name       its name
      @param help_text  its help
      @param run        its function
      @param file       whether it takes the FILE argument (and --system)
      @return its parser
      """
      q = a.add_parser(name, help=help_text)
      if file:
         q.add_argument("file", metavar="FILE", help="the manifest")
         q.add_argument("--system", help="the system (default: the one that edits the manifest's schema)")
      q.set_defaults(run=run)
      return q

   q = action("systems", "the systems and what they edit", cmd_systems, file=False)
   q.add_argument("--all", action="store_true", help="also the dev-only systems")
   q = action("new", "a new manifest of a system", cmd_new, file=False)
   q.add_argument("file", metavar="FILE")
   q.add_argument("--system", required=True)
   q = action("show", "elements, links, live values and problems", cmd_show)
   q.add_argument("--json", action="store_true", help="print JSON")
   action("check", "the problems (exit status 1 on errors)", cmd_check)
   q = action("kinds", "the palette", cmd_kinds)
   q.add_argument("--from", dest="wire_from", metavar="ELEMENT.PORT",
                  help="only kinds a wire from this port can end on")
   q = action("add", "add an element from the palette", _edit(lambda s, x: s.add(
      x.kind, x.at, _assignments(x.set), x.id, x.frame)))
   q.add_argument("kind")
   q.add_argument("--at", type=_pair, required=True, metavar="X,Y")
   q.add_argument("--set", action="append", default=[], metavar="FIELD=VALUE")
   q.add_argument("--id", help="its id (default: a new one)")
   q.add_argument("--frame", help="the frame to put it in (default: the one it lies in)")
   q = action("add-wired", "add a node wired to a port", _edit(lambda s, x: s.add_wired(
      x.kind, x.at, Endpoint.parse(x.wire_from), x.port)))
   q.add_argument("kind")
   q.add_argument("--at", type=_pair, required=True, metavar="X,Y")
   q.add_argument("--from", dest="wire_from", required=True, metavar="ELEMENT.PORT")
   q.add_argument("--port", help="the new node's port (default: the first that fits)")
   q = action("remove", "remove elements or links", _edit(cmd_remove))
   q.add_argument("ids", nargs="+", metavar="ID")
   q = action("move", "move elements", _edit(cmd_move))
   q.add_argument("ids", nargs="+", metavar="ID")
   g = q.add_mutually_exclusive_group(required=True)
   g.add_argument("--by", type=_pair, metavar="DX,DY")
   g.add_argument("--to", type=_pair, metavar="X,Y", help="the first element's corner (the others keep their place "
                                                           "relative to it)")
   q = action("resize", "set an element's size", _edit(lambda s, x: s.resize(x.id, x.size)))
   q.add_argument("id")
   q.add_argument("--size", type=_pair, required=True, metavar="W,H")
   q = action("set", "set inspector fields", _edit(lambda s, x: s.set_properties(x.id, _assignments(x.values))))
   q.add_argument("id")
   q.add_argument("values", nargs="+", metavar="FIELD=VALUE")
   q = action("connect", "wire two ports, or connect two elements", _edit(lambda s, x: s.connect(
      Endpoint.parse(x.source), Endpoint.parse(x.target), x.label)))
   q.add_argument("source", metavar="FROM")
   q.add_argument("target", metavar="TO")
   q.add_argument("--label", default="")
   q = action("disconnect", "remove links", _edit(lambda s, x: s.disconnect(x.ids)))
   q.add_argument("ids", nargs="+", metavar="LINK")
   q = action("label", "set a link's text", _edit(lambda s, x: s.set_label(x.id, x.text)))
   q.add_argument("id", metavar="LINK")
   q.add_argument("text")
   q = action("frame", "put elements into a frame, or take them out", _edit(
      lambda s, x: s.set_frame(x.ids, None if x.out else x.into)))
   q.add_argument("ids", nargs="+", metavar="ID")
   g = q.add_mutually_exclusive_group(required=True)
   g.add_argument("--into", metavar="FRAME")
   g.add_argument("--out", action="store_true")
   q = action("duplicate", "copy elements and the wires between them", _edit(
      lambda s, x: s.duplicate(x.ids, x.offset)))
   q.add_argument("ids", nargs="+", metavar="ID")
   q.add_argument("--offset", type=_pair, default=DUPLICATE_OFFSET, metavar="DX,DY")
   q = action("align", "line elements up on the first", _edit(lambda s, x: s.align(x.ids, x.edge)))
   q.add_argument("edge", choices=ops.ALIGN_EDGES)
   q.add_argument("ids", nargs="+", metavar="ID")
   q = action("distribute", "space elements evenly", _edit(lambda s, x: s.distribute(x.ids, x.axis)))
   q.add_argument("axis", choices=(ops.HORIZONTAL, ops.VERTICAL))
   q.add_argument("ids", nargs="+", metavar="ID")
   q = action("same-size", "give elements the first one's size", _edit(lambda s, x: s.same_size(x.ids, x.which)))
   q.add_argument("which", choices=(ops.SAME_WIDTH, ops.SAME_HEIGHT, ops.SAME_BOTH))
   q.add_argument("ids", nargs="+", metavar="ID")
   q = action("front", "draw elements over the others", _edit(lambda s, x: s.to_front(x.ids)))
   q.add_argument("ids", nargs="+", metavar="ID")
   q = action("back", "draw elements under the others", _edit(lambda s, x: s.to_back(x.ids)))
   q.add_argument("ids", nargs="+", metavar="ID")
   action("layout", "tidy up: the system's nodes in ranks", _edit(lambda s, x: s.auto_layout() and None))


def cmd_systems(args: argparse.Namespace) -> int:
   """!Lists the systems.
   @param args  parsed arguments
   @return 0
   """
   for s in registry.systems(include_dev=args.all):
      dev = " (dev only)" if s.dev_only else ""
      print(f"{s.system_id}: {s.title}{dev} - {s.schema}: {s.description}")
   return 0


def cmd_new(args: argparse.Namespace) -> int:
   """!Writes a new manifest.
   @param args  parsed arguments
   @return 0
   """
   from pathlib import Path
   if Path(args.file).exists():
      raise CommandError(f"{args.file} exists already")
   DesignSession.new(args.system, args.file).save()
   print(f"new {registry.get(args.system).title} manifest: {args.file}")
   return 0


def cmd_show(args: argparse.Namespace) -> int:
   """!Prints the diagram.
   @param args  parsed arguments
   @return 0
   """
   s = _session(args)
   diagram = s.diagram()
   values = s.live_values()
   problems = s.diagnostics()
   if args.json:
      out = diagram.to_json()
      out["values"] = values
      out["problems"] = [p.to_json() for p in problems]
      print(json.dumps(out, indent=JSON_INDENT))
      return 0
   print(f"{s.system.title}: {len(diagram.elements)} elements, {len(diagram.links)} links")
   for e in diagram.elements.values():
      kind = s.system.kind(e.kind) if e.kind in {k.kind_id for k in s.system.kinds()} else None
      title = kind.title if kind is not None else e.kind
      w, h = s.system.element_size(e) if kind is not None else e.size
      extra = [f"in {e.parent}"] if e.parent else []
      text = s.system.node_text(e)
      if text:
         extra.append(text)
      if e.element_id in values:
         extra.append(f"= {values[e.element_id]}")
      tail = f" ({'; '.join(extra)})" if extra else ""
      print(f"  {e.element_id}: {title} at {e.pos[0]},{e.pos[1]} size {w}x{h}{tail}")
   for k in diagram.links.values():
      label = f" \"{k.label}\"" if k.label else ""
      print(f"  {k.link_id}: {k.source.text()} -> {k.target.text()}{label}")
   for p in problems:
      print(f"{p.severity}: {p.message}")
   return 0


def cmd_check(args: argparse.Namespace) -> int:
   """!Prints the problems.
   @param args  parsed arguments
   @return 0, or ERROR_STATUS when there are errors
   """
   problems = _session(args).diagnostics()
   for p in problems:
      print(f"{p.severity}: {p.message}")
   if not problems:
      print("no problems")
   return ERROR_STATUS if checks.errors(problems) else 0


def cmd_kinds(args: argparse.Namespace) -> int:
   """!Prints the palette.
   @param args  parsed arguments
   @return 0
   """
   s = _session(args)
   fitting = set(s.fitting_kinds(Endpoint.parse(args.wire_from))) if args.wire_from else None
   for k in s.system.kinds():
      if fitting is not None and k.kind_id not in fitting:
         continue
      ports = ", ".join(f"{p.side} {p.name}: {p.data_type}" for p in k.ports)
      fields = ", ".join(p.name for p in k.properties)
      detail = "; ".join(x for x in (ports, f"fields {fields}" if fields else "") if x)
      print(f"{k.kind_id}: {k.title} [{k.category}]" + (f" - {detail}" if detail else ""))
   return 0


def cmd_remove(s: DesignSession, args: argparse.Namespace) -> list[str]:
   """!Removes the elements and links named.
   @param s     the session
   @param args  parsed arguments
   @return the elements removed
   """
   diagram = s.diagram()
   unknown = [i for i in args.ids if i not in diagram.elements and i not in diagram.links]
   if unknown:
      raise CommandError("no element or link " + ", ".join(unknown))
   return s.remove([i for i in args.ids if i in diagram.elements], [i for i in args.ids if i in diagram.links])


def cmd_move(s: DesignSession, args: argparse.Namespace) -> None:
   """!Moves elements by an offset, or the first to a position (the others with it).
   @param s     the session
   @param args  parsed arguments
   @return None
   """
   if args.by is not None:
      s.move(args.ids, args.by[0], args.by[1])
      return
   first = s.diagram().element(args.ids[0])
   s.move(args.ids, args.to[0] - first.pos[0], args.to[1] - first.pos[1])
