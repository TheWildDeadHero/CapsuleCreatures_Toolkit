"""!Commands for whole manifests: validate."""
from __future__ import annotations

import argparse

from ..core.document import Document


def register(sub: argparse._SubParsersAction) -> None:
   """!Adds the command group.
   @param sub  argparse subparsers
   @return None
   """
   p = sub.add_parser("validate", help="compile every asset with the engine's compiler and report problems")
   p.add_argument("manifest")
   p.add_argument("-q", "--quiet", action="store_true", help="print problems only")
   p.set_defaults(run=validate)


def validate(args: argparse.Namespace) -> int:
   """!Prints each asset's state.
   @param args  parsed arguments
   @return 0 when everything compiles, 1 otherwise
   """
   doc = Document.open(args.manifest)
   problems, reports = doc.validate()
   for msg in problems:
      print(f"error: {msg}")
   for key, r in reports.items():
      if not r.ok:
         print(f"error: {key}: {r.error}")
      elif not args.quiet:
         extra = f" ({r.compiled['tiles_total']} tiles)" if r.compiled else ""
         print(f"ok: {key}{extra}")
   bad = len(problems) + sum(1 for r in reports.values() if not r.ok)
   if not args.quiet:
      print(f"{len(reports)} assets, {bad} with problems")
   return 1 if bad else 0
