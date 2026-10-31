#!/usr/bin/env python3
"""!The studio runs on Python 3.10 and newer (the project minimum, sync35): no
f-string may reuse its own quote inside a replacement field, which only
Python 3.12 (PEP 701) reads (the two cases sync35 fixed were
core/field_rules.py:463 and core/placeholders.py:298). Every .py file under
editor/ and toolkit/ is read with the tokenizer of the running Python: on
3.12 and newer its f-string tokens show the nesting; on older ones the file
must simply parse.
"""
from __future__ import annotations

import ast
import io
import sys
import tokenize
import unittest
from pathlib import Path

## Repository root.
ROOT = Path(__file__).resolve().parent.parent.parent
## The folders whose Python files are checked.
CHECKED = ("editor", "toolkit")
## Folders never read (bytecode caches, environments).
SKIPPED = {"__pycache__", ".venv"}
## The oldest Python the studio supports.
MINIMUM = (3, 10)
## Characters that may come before a string literal's quote (r, b, u, f and their capitals).
PREFIX_CHARS = "rRbBuUfF"
## Length of a triple quote.
TRIPLE = 3
## The two lines sync35 fixed, as they read before (each reuses its f-string's quote inside a field).
FIXED_CASES = ('x = f"{", ".join(names)}"\n', "y = f'{d['key']}'\n")


def quote_of(text: str) -> str:
   """!The quote a string token starts with (its prefix left out).
   @param text  the token text (a STRING or an FSTRING_START token)
   @return the quote: one or three quote characters
   """
   body = text.lstrip(PREFIX_CHARS)
   return body[:TRIPLE] if body[:TRIPLE] in ('"""', "'''") else body[:1]


def clashes(outer: str, inner: str) -> bool:
   """!Whether a string inside an f-string's field ends the outer one for a Python before 3.12.
   @param outer  the outer f-string's quote
   @param inner  the inner string's quote
   @return True when the inner one starts with the outer's quote (a single quote: its character; a triple: all three)
   """
   return inner.startswith(outer)


def nested_quotes(source: str) -> list[tuple[int, str]]:
   """!The strings inside an f-string's replacement field that reuse the f-string's quote (Python 3.12 tokens).
   @param source  Python source text
   @return (line, text) per clash
   """
   out: list[tuple[int, str]] = []
   start, end = tokenize.FSTRING_START, tokenize.FSTRING_END
   open_quotes: list[str] = []
   for tok in tokenize.generate_tokens(io.StringIO(source).readline):
      if tok.type in (start, tokenize.STRING) and any(clashes(q, quote_of(tok.string)) for q in open_quotes):
         out.append((tok.start[0], tok.string))
      if tok.type == start:
         open_quotes.append(quote_of(tok.string))
      elif tok.type == end:
         open_quotes.pop()
   return out


def python_files() -> list[Path]:
   """!The checked Python files.
   @return paths, sorted
   """
   out = []
   for folder in CHECKED:
      for path in sorted((ROOT / folder).rglob("*.py")):
         if not SKIPPED & set(path.relative_to(ROOT).parts):
            out.append(path)
   return out


class PythonCompatTests(unittest.TestCase):
   """!Python 3.10 compatibility of the studio's code."""

   def test_no_nested_same_quote_fstrings(self) -> None:
      """!No f-string reuses its quote inside a field (3.12 tokens), or every file parses (older Pythons).
      @return None
      """
      found = []
      files = python_files()
      self.assertTrue(files)
      for path in files:
         source = path.read_text(encoding="utf-8")
         rel = path.relative_to(ROOT).as_posix()
         if hasattr(tokenize, "FSTRING_START"):
            found += [f"{rel}:{line}: {text}" for line, text in nested_quotes(source)]
         else:
            try:
               ast.parse(source, rel)
            except SyntaxError as e:
               found.append(f"{rel}:{e.lineno}: {e.msg}")
      self.assertEqual(found, [], f"Python {MINIMUM[0]}.{MINIMUM[1]} cannot read these f-strings")

   @unittest.skipUnless(hasattr(tokenize, "FSTRING_START"), "needs Python 3.12 tokens")
   def test_guard_sees_the_fixed_cases(self) -> None:
      """!The two sync35 cases are found; a field with the other quote, or a triple-quoted f-string holding a
      single quote of its character, is fine.
      @return None
      """
      for case in FIXED_CASES:
         self.assertEqual(len(nested_quotes(case)), 1, case)
      self.assertEqual(nested_quotes('x = f"{\', \'.join(names)}"\n'), [])
      self.assertEqual(nested_quotes('x = f"""{d["key"]}"""\n'), [])

   def test_minimum_runs(self) -> None:
      """!The running Python is at least the minimum (the suite's own code needs no newer one).
      @return None
      """
      self.assertGreaterEqual(sys.version_info[:len(MINIMUM)], MINIMUM)


if __name__ == "__main__":
   unittest.main()
