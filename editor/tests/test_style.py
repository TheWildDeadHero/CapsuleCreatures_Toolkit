#!/usr/bin/env python3
"""!The studio's code follows the project style (toolkit/check_style.py): 3-space indents, names, type annotations
and no magic numbers, in the editor, the toolkit, the installers and the launchers."""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

## Repository root.
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "toolkit"))
import check_style  # noqa: E402

## What is checked: folders, and the launchers in the root.
CHECKED = ["editor", "toolkit", "install"] + sorted(
   p.name for p in ROOT.iterdir() if p.is_file() and check_style.kind_of(p) is not None)


class StyleTests(unittest.TestCase):
   """!The whole repository."""

   def test_style(self) -> None:
      """!No style problems (the message lists them)."""
      problems = check_style.check([ROOT / p for p in CHECKED])
      shown = "\n".join(str(p) for p in problems[:50])
      self.assertEqual(problems, [], f"{len(problems)} style problem(s), first ones:\n{shown}")

   def test_command_line(self) -> None:
      """!The checker's command line reports and fails on a problem."""
      out, err = io.StringIO(), io.StringIO()
      with tempfile.TemporaryDirectory(prefix="capsule_style_") as folder:
         bad = Path(folder) / "sample.py"
         bad.write_text("def f(x):\n    return x\n", encoding="utf-8")
         with redirect_stdout(out), redirect_stderr(err):
            status = check_style.main([str(bad)])
      self.assertEqual(status, 1)
      self.assertIn("indent", out.getvalue())
      self.assertIn("annotation", out.getvalue())


if __name__ == "__main__":
   unittest.main()
