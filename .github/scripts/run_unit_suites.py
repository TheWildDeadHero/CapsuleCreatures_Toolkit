#!/usr/bin/env python3
"""!Runs the editor's unit suites one test file per process, as `unittest discover` would run them together.

One process for every suite keeps growing: the Qt smoke tests open hundreds of windows, and the whole run reached
more than 4.5 GB in one process (D-40 RC), beyond a 7 GB macOS runner once the system's share is counted. A fresh
process per file returns that memory after each file. Each file runs exactly as discover finds it
(`-m unittest discover -s tests -p <file>`), so imports and skips are unchanged.

Usage: run_unit_suites.py [--python PYTHON] [--tests DIR] [PATTERN]

PYTHON defaults to this interpreter, DIR to tests/ (run from editor/), PATTERN to test_*.py. Prints one line per
file and a summary; exits 1 when any file failed or could not run. On GitHub Actions (GITHUB_ACTIONS set) every
failed file also gets an error annotation with the end of its output, readable without the raw log.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

## Exit status when every file passed.
EXIT_OK = 0
## Exit status when a file failed.
EXIT_FAILED = 1
## Output lines kept per failed file in its annotation.
ANNOTATION_LINES = 60


def run_file(python: str, tests: Path, name: str) -> tuple[int, float, str]:
   """!Runs one test file in its own process and echoes its output.
   @param python  the interpreter (the toolkit environment's)
   @param tests   the tests folder (discover's start directory)
   @param name    the file's name, e.g. test_core.py
   @return (exit status, seconds taken, its output)
   """
   start = time.monotonic()
   done = subprocess.run([python, "-m", "unittest", "discover", "-s", str(tests), "-p", name],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
   sys.stdout.write(done.stdout)
   sys.stdout.flush()
   return done.returncode, time.monotonic() - start, done.stdout


def annotate(name: str, output: str) -> None:
   """!Writes a GitHub error annotation for a failed file (only on GitHub Actions).
   @param name    the file's name
   @param output  its output
   @return None
   """
   if not os.environ.get("GITHUB_ACTIONS"):
      return
   tail = "\n".join(output.splitlines()[-ANNOTATION_LINES:])
   text = tail.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
   print(f"::error title=unit {name}::{text}", flush=True)


def main(argv: list[str] | None = None) -> int:
   """!Command-line entry point; see the module docstring.
   @param argv  arguments without the program name, or None for sys.argv
   @return exit status
   """
   p = argparse.ArgumentParser(description="Run the unit suites one test file per process.")
   p.add_argument("--python", default=sys.executable, help="interpreter to run them with (default: this one)")
   p.add_argument("--tests", default="tests", help="the tests folder (default: tests)")
   p.add_argument("pattern", nargs="?", default="test_*.py", help="test files (default: test_*.py)")
   args = p.parse_args(argv)

   tests = Path(args.tests)
   files = sorted(f.name for f in tests.glob(args.pattern))
   if not files:
      print(f"error: no {args.pattern} in {tests}", file=sys.stderr)
      return EXIT_FAILED
   failed: list[str] = []
   total = 0.0
   for name in files:
      # The header goes to stdout before unittest's own (stderr) report, so flush to keep them in order.
      print(f"== {name}", flush=True)
      status, seconds, output = run_file(args.python, tests, name)
      total += seconds
      print(f"-- {name}: {'ok' if status == EXIT_OK else f'FAILED (exit {status})'} in {seconds:.1f} s", flush=True)
      if status != EXIT_OK:
         failed.append(name)
         annotate(name, output)
   print(f"{len(files) - len(failed)} of {len(files)} test files passed in {total:.0f} s")
   for name in failed:
      print(f"FAILED: {name}")
   return EXIT_FAILED if failed else EXIT_OK


if __name__ == "__main__":
   sys.exit(main())
