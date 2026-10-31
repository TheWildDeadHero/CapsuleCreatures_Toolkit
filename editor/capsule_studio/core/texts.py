"""!Text and credits editing.

Text assets are strings in the game's code page (core.codepage: the
project's page, or the engine's ASCII page) and newlines. Credits are pages of a heading and a block of names, stored as
pairs of text assets the credits sequence refers to:

    text:<PREFIX> HEAD 01   / text:<PREFIX> NAMES 01
    text:<PREFIX> HEAD 02   / text:<PREFIX> NAMES 02  ...

so editing the credits never touches the sequence: page n is always the
pair numbered n. The prefix defaults to "CREDITS".

Functions that change a Document must be called inside doc.edit().
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from . import codepage

if TYPE_CHECKING:
   from .document import Document
   from .manifest_io import JsonDict

## A credits page: (heading, names).
CreditsPage = tuple[str, str]

## Default credits key prefix.
CREDITS_PREFIX = "CREDITS"
## Visible text columns on a 240-pixel screen with 8-pixel glyphs.
SCREEN_COLUMNS = 30
## Visible text rows on a 160-pixel screen.
SCREEN_ROWS = 20
## Lines of names a credits page shows (rows 16-19 under the heading on row 14).
CREDITS_NAMES_ROWS = 4
## Fewest digits of a credits page number in its keys (zero-padded: "01").
CREDITS_DIGITS = 2
## Regex group of a credits key's part (HEAD or NAMES), see _credits_pattern().
PART_GROUP = 1
## Regex group of a credits key's page number, see _credits_pattern().
NUMBER_GROUP = 2


def bad_characters(text: str, page: Any = None) -> list[str]:
   """!Characters the game cannot show: those its code page neither maps nor aliases.
   @param text  string
   @param page  text_encoder.CodePage (core.codepage.load()), or None for the engine's default page
   @return sorted list of distinct characters outside the code page
   """
   return sorted(codepage.unmapped(page if page is not None else codepage.default_page(), text))


def check_text(text: str, columns: int = SCREEN_COLUMNS, rows: int | None = None, page: Any = None) -> list[str]:
   """!Problems with a text for where it will be shown.
   @param text     string
   @param columns  usable columns (30 for a full layer; box width - 2 in a box)
   @param rows     usable rows, or None not to check
   @param page     text_encoder.CodePage, or None for the engine's default page
   @return list of messages (errors start with "error:", the rest are warnings)
   """
   page = page if page is not None else codepage.default_page()
   out = []
   bad = bad_characters(text, page)
   if bad:
      out.append(f"error: not in the code page {page.id!r}: " + " ".join(repr(c) for c in bad))
   lines = text.split("\n")
   for i, line in enumerate(lines):
      # Cells, not characters: an alias may print several codes, a letter with a mark one.
      width = len(codepage.cells(page, line))
      if width > columns:
         out.append(f"line {i + 1} is {width} characters; {columns} fit")
   if rows is not None and len(lines) > rows:
      out.append(f"{len(lines)} lines; {rows} fit")
   return out


def credits_keys(prefix: str, n: int, digits: int = CREDITS_DIGITS) -> tuple[str, str]:
   """!The heading and names keys of one credits page.
   @param prefix  key prefix, e.g. "CREDITS"
   @param n       page number, from 1
   @param digits  zero-padding of the number
   @return (heading key, names key)
   """
   num = str(n).zfill(digits)
   return f"text:{prefix} HEAD {num}", f"text:{prefix} NAMES {num}"


def _credits_pattern(prefix: str) -> re.Pattern[str]:
   """!Regex for the keys of a credits prefix.
   @param prefix  key prefix
   @return compiled pattern; groups: part (HEAD/NAMES), number
   """
   return re.compile(r"^text:" + re.escape(prefix) + r" (HEAD|NAMES) (\d+)$", re.IGNORECASE)


def is_credits_key(key: str | None, prefix: str = CREDITS_PREFIX) -> bool:
   """!Whether a key belongs to a credits page.
   @param key     asset key
   @param prefix  credits prefix
   @return True or False
   """
   return bool(_credits_pattern(prefix).match(key or ""))


def credits_pages(doc: Document, prefix: str = CREDITS_PREFIX) -> list[CreditsPage]:
   """!The credits pages, in number order. A page with only one half
   present gets an empty string for the other.
   @param doc     Document
   @param prefix  credits prefix
   @return list of (heading, names)
   """
   pat, pages = _credits_pattern(prefix), {}
   for a in doc.assets("text"):
      m = pat.match(a.get("key", ""))
      if m:
         page = pages.setdefault(int(m.group(NUMBER_GROUP)), ["", ""])
         page[0 if m.group(PART_GROUP).upper() == "HEAD" else 1] = a.get("text", "")
   return [tuple(pages[n]) for n in sorted(pages)]


def set_credits_pages(doc: Document, pages: Sequence[CreditsPage], prefix: str = CREDITS_PREFIX) -> None:
   """!Replaces the credits with these pages, numbered from 1. The new text
   assets take the place of the first old credits asset in the manifest
   (or go at the end when there were none).
   @param doc     Document
   @param pages   list of (heading, names)
   @param prefix  credits prefix
   @return None
   """
   if any(not isinstance(h, str) or not isinstance(n, str) for h, n in pages):
      raise ValueError("credits headings and names must be strings")
   pat, assets = _credits_pattern(prefix), doc.data["assets"]
   # The new pages go where the first old credits asset was: its index among the assets that stay.
   first = next((i for i, a in enumerate(assets) if a.get("kind") == "text" and pat.match(a.get("key", ""))), None)
   kept = [a for a in assets if not (a.get("kind") == "text" and pat.match(a.get("key", "")))]
   at = len(kept) if first is None else first - sum(
      1 for a in assets[:first] if a.get("kind") == "text" and pat.match(a.get("key", "")))
   digits = max(CREDITS_DIGITS, len(str(len(pages))))
   new = []
   for n, (heading, names) in enumerate(pages, 1):
      hk, nk = credits_keys(prefix, n, digits)
      new += [{"key": hk, "kind": "text", "text": heading}, {"key": nk, "kind": "text", "text": names}]
   doc.data["assets"] = kept[:at] + new + kept[at:]
   for a in new:   # collisions with unrelated assets, after the engine's canonicalisation
      doc.check_new_key(a["key"], ignore=a)


def parse_credits_text(source: str) -> list[CreditsPage]:
   """!Reads credits from plain text: pages separated by blank lines, the
   first line of each page its heading, the rest its names.

       DIRECTOR
       A. Person

       PROGRAMMING
       B. Person
       C. Person

   @param source  the text
   @return list of (heading, names)
   """
   pages, block = [], []
   # The extra blank line at the end closes the last page.
   for line in source.replace("\r\n", "\n").split("\n") + [""]:
      if line.strip():
         block.append(line.rstrip())
      elif block:
         pages.append((block[0].strip(), "\n".join(block[1:])))
         block = []
   return pages


def format_credits_text(pages: Sequence[CreditsPage]) -> str:
   """!Writes credits as plain text (the parse_credits_text() format).
   @param pages  list of (heading, names)
   @return the text
   """
   return "\n\n".join(h + ("\n" + n if n else "") for h, n in pages) + ("\n" if pages else "")


def set_text(doc: Document, key: str, text: str) -> JsonDict:
   """!Sets a text asset's string, creating the asset when needed.
   @param doc   Document
   @param key   "text:NAME"
   @param text  string
   @return the asset
   """
   if not isinstance(text, str):
      raise ValueError("a text must be a string")
   a = doc.find(key)
   if a is None:
      return doc.add_asset({"key": key, "kind": "text", "text": text})
   if a.get("kind") != "text":
      raise ValueError(f"{key!r} is a {a.get('kind')}, not a text")
   a["text"] = text
   return a
