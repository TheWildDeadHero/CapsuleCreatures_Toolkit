"""!A game's code page (C-2, D-20): which 8-bit code each character of its
language gets, and the characters its texts use that the page lacks.

The engine's tools/text_encoder.py is the one authority on code pages
(capsule.codepage/1): this module loads and checks pages with it, so the
editor accepts exactly what the build accepts. A game names its page in
reference/project.json:

    "text": {"language": "en", "code_pages": {"en": "data/text/en.codepage.json"},
             "fonts": {"en": "<font>.txt" or [base font, extra glyph files...]}}

(paths relative to the game folder); without one it uses the engine's ASCII
page. What this module adds for editors: finding a file's project, the page
and fonts of a project, every text of the project with where it is, the
characters missing from the page, the cells a text takes, and edits of a
page's codes and aliases (set_code(), unset_code(), set_alias(); call them
inside the page Document's edit()). Qt-free; the text commands, the text
checks (core.texts), previews (core.preview) and the code page panel use it.
"""
from __future__ import annotations

import re
import types
import unicodedata
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from . import engine, manifest_io
from .document import Document, DocumentError

## Code page manifest schema.
SCHEMA = "capsule.codepage/1"
## Project manifest schema.
PROJECT_SCHEMA = "capsule.project/1"
## Folder of a game holding its project manifest.
REFERENCE_FOLDER = "reference"
## File name of a project manifest.
PROJECT_FILE = "project.json"
## Folder (relative to the game folder) import_page() copies a page into.
PAGE_FOLDER = "data/text"
## File name suffix of a code page.
PAGE_SUFFIX = ".codepage.json"
## Font of a language that names none (relative to the engine root).
DEFAULT_FONT = "assets/fonts/default_8x8.txt"
## Codes a page row shows (show() prints the page as 16 rows of 16).
ROW_CODES = 16
## A placeholder or other markup item in a text that allows markup (`{name}`, `{@concept}`).
MARKUP_ITEM = re.compile(r"\{[^{}]*\}")
## Battle lists whose entries have a "texts" object.
BATTLE_TEXT_OBJECTS = ("statuses", "weathers")
## Condition record lists of battle data (E5; no editor list of their own yet) with the word "where" uses: their
## names and "texts" (a text, or {"message": NAME} naming an engine message) are in-game texts too.
BATTLE_CONDITION_RECORDS = {"volatiles": "volatile", "side_conditions": "side condition",
                            "field_conditions": "field condition"}

## A use of text in a project: (where, the text, whether it allows markup).
TextUse = tuple[str, str, bool]
## One piece of a text as the page encodes it: (the text, its codes or None when the page lacks it).
Piece = tuple[str, list[int] | None]


def encoder() -> types.ModuleType:
   """!The engine's text encoder module.
   @return module
   """
   return engine.tool("text_encoder")


def default_page() -> Any:
   """!The engine's default code page (printable ASCII).
   @return text_encoder.CodePage
   """
   return encoder().DEFAULT


# -- projects ----------------------------------------------------------------------------------

def find_project(path: str | Path) -> Path | None:
   """!The project manifest a path belongs to: the path itself when it is
   one, else the first reference/project.json in it or above it.
   @param path  a project.json, a game folder, or any file or folder in a game
   @return the project.json, or None when there is none
   """
   p = Path(path).resolve()
   if p.is_file() and p.name == PROJECT_FILE and p.parent.name == REFERENCE_FOLDER:
      return p
   for folder in [p] + list(p.parents):
      candidate = folder / REFERENCE_FOLDER / PROJECT_FILE
      if candidate.is_file():
         return candidate
   return None


def open_project(path: str | Path) -> Document:
   """!Opens the project a path belongs to (see find_project()).
   @param path  a project.json, a game folder, or a file in a game
   @return project Document
   @throws DocumentError when there is none
   """
   found = find_project(path)
   if found is None:
      raise DocumentError(f"{path}: no {REFERENCE_FOLDER}/{PROJECT_FILE} in it or above it")
   try:
      return Document.open(found, PROJECT_SCHEMA)
   except (OSError, ValueError) as e:
      raise DocumentError(f"cannot read {found}: {e}") from e


def game_folder(project: Document) -> Path:
   """!The folder the project's paths are relative to (the one holding reference/).
   @param project  project Document (opened from a file)
   @return Path
   """
   if project.path is None:
      raise DocumentError("the project manifest has not been saved yet")
   return project.path.parent.parent


def _text_section(project: Document) -> dict[str, Any]:
   """!The project's "text" object.
   @param project  project Document
   @return the object ({} when absent)
   """
   t = project.data.get("text")
   if t is None:
      return {}
   if not isinstance(t, dict):
      raise DocumentError(f"{project.path.name if project.path else 'project'}: \"text\" must be an object")
   return t


def language(project: Document) -> str | None:
   """!The game's language.
   @param project  project Document
   @return its id ("en"), or None when the project names none (the engine's ASCII page)
   """
   lang = _text_section(project).get("language")
   return lang if isinstance(lang, str) and lang else None


def page_path(project: Document) -> Path | None:
   """!The file of the project's code page.
   @param project  project Document
   @return absolute Path, or None when the game uses the engine's default page
   """
   lang = language(project)
   if lang is None:
      return None
   rel = (_text_section(project).get("code_pages") or {}).get(lang)
   if not isinstance(rel, str) or not rel:
      raise DocumentError(f"{project.path.name}: text.code_pages names no code page for the language {lang!r}")
   return (game_folder(project) / rel).resolve()


def font_files(project: Document | None) -> list[Path]:
   """!The font files of the project's language (the first is the font, the others add glyphs).
   @param project  project Document, or None
   @return absolute Paths (the engine's default font when the project names none)
   """
   default = [engine.root() / DEFAULT_FONT]
   lang = language(project) if project is not None else None
   if lang is None:
      return default
   given = (_text_section(project).get("fonts") or {}).get(lang)
   if given is None:
      return default
   names = given if isinstance(given, list) else [given]
   return [(game_folder(project) / n).resolve() for n in names]


def load(project: Document | None) -> Any:
   """!The project's code page.
   @param project  project Document, or None for the engine's default
   @return text_encoder.CodePage
   @throws DocumentError when the page cannot be read or is invalid
   """
   path = page_path(project) if project is not None else None
   if path is None:
      return default_page()
   te = encoder()
   try:
      return te.CodePage.load(path)
   except te.TextError as e:
      raise DocumentError(str(e)) from None


def for_file(path: str | Path) -> Any:
   """!The code page of the game a file belongs to (the engine's default outside any game).
   @param path  any file or folder
   @return text_encoder.CodePage
   """
   found = find_project(path)
   return load(open_project(found)) if found is not None else default_page()


def glyphs(project: Document | None, page: Any = None) -> dict[int, list[list[int]]]:
   """!The font cells of the project's language, by code.
   @param project  project Document, or None for the engine's default page and font
   @param page     its code page (loaded when None)
   @return dict code -> 8x8 cell (see engine.font_glyphs())
   """
   page = page if page is not None else load(project)
   return engine.font_glyphs(page, font_files(project))


def font_problems(project: Document | None, page: Any = None) -> list[str]:
   """!What the build's font compiler refuses: characters the page maps
   that the language's fonts have no glyph for, unreadable font files.
   @param project  project Document, or None
   @param page     its code page (loaded when None)
   @return messages ([] when the font compiles)
   """
   page = page if page is not None else load(project)
   fc, te = engine.tool("font_compiler"), encoder()
   try:
      files = font_files(project)
      chars = fc.parse_characters(files[0])
      for more in files[1:]:
         chars = fc.merge(chars, fc.parse_characters(more), more)
      fc.layout(chars, page)
   except (te.TextError, OSError, SystemExit) as e:   # font_compiler.fail() exits with a message
      return [str(e) or f"the font files do not compile: {', '.join(str(f) for f in font_files(project))}"]
   return []


# -- encoding ----------------------------------------------------------------------------------

def _grapheme(text: str, i: int) -> str:
   """!The character at a position with the combining marks that follow it.
   @param text  NFC text
   @param i     position
   @return the character
   """
   j = i + 1
   while j < len(text) and unicodedata.combining(text[j]):
      j += 1
   return text[i:j]


def pieces(page: Any, text: str) -> list[Piece]:
   """!A line of plain text (no markup, no newline) as the page encodes it,
   longest match first (aliases included).
   @param page  text_encoder.CodePage
   @param text  the text
   @return list of (text, codes), codes None for a character the page lacks
   """
   text = unicodedata.normalize(encoder().NORMAL_FORM, text)
   table = page.table   # text -> codes: mapped characters and aliases
   out = []
   i = 0
   while i < len(text):
      for n in range(min(page.longest, len(text) - i), 0, -1):
         codes = table.get(text[i:i + n])
         if codes is not None:
            out.append((text[i:i + n], list(codes)))
            i += n
            break
      else:
         g = _grapheme(text, i)
         out.append((g, None))
         i += len(g)
   return out


def cells(page: Any, line: str) -> list[int | None]:
   """!The codes a line of plain text prints, one per cell.
   @param page  text_encoder.CodePage
   @param line  the text (no newline)
   @return codes; None for a cell whose character the page lacks
   """
   out: list[int | None] = []
   for _text, codes in pieces(page, line):
      out += codes if codes is not None else [None]
   return out


def unmapped(page: Any, text: str) -> list[str]:
   """!Characters of a plain text (newlines aside) the page cannot encode.
   @param page  text_encoder.CodePage
   @param text  the text
   @return the distinct characters, in order of first appearance
   """
   out = []
   for line in text.split("\n"):
      for piece, codes in pieces(page, line):
         if codes is None and piece not in out:
            out.append(piece)
   return out


def plain(text: str, terms: Any = None) -> str:
   """!A text that allows markup as its characters reach the page: terms
   expanded (`{@concept}`), placeholders (`{name}`) left out.
   @param text   the text
   @param terms  {concept: {"one", "many"}} for {@concept}, or None
   @return the text
   """
   te = encoder()
   try:
      text = te.expand_terms(text, "text", terms)
   except te.TextError:
      pass   # the compiler reports bad terms; the characters around them still count
   return MARKUP_ITEM.sub("", text)


# -- the project's texts -----------------------------------------------------------------------

def _load_json(path: Path) -> Any:
   """!A manifest, or None when it cannot be read.
   @param path  file
   @return the parsed JSON, or None
   """
   try:
      return manifest_io.load(path)
   except (OSError, ValueError):
      return None


def _asset_texts(path: Path) -> Iterator[TextUse]:
   """!Text assets of an asset manifest.
   @param path  assets.json
   @return iterator of TextUse
   """
   data = _load_json(path)
   for a in (data or {}).get("assets", []) if isinstance(data, dict) else []:
      if isinstance(a, dict) and a.get("kind") == "text" and isinstance(a.get("text"), str):
         yield f"assets: {a.get('key')}", a["text"], False


def battle_entry_texts() -> dict[str, tuple[str, ...]]:
   """!Battle texts per entry kind: the keys of a battle list entry that hold texts besides "name" (a presenter's,
   the engine's PRESENTER_TEXTS: intro, defeat, victory; E13b).
   @return {list key: text keys}
   """
   return {"presenters": tuple(engine.tool("battle_compiler").PRESENTER_TEXTS)}


def _battle_texts(path: Path) -> Iterator[TextUse]:
   """!Names, messages and texts of battle data: the battle manifest and the structure manifest it names, read as
   one (the engine's view_of(); a single-file manifest, the form before E5s, is read as it is).
   @param path  battle.json
   @return iterator of TextUse
   """
   from . import battle   # battle imports nothing from here; kept local so this module loads alone

   bc = engine.tool("battle_compiler")
   try:
      data = bc.view_of(path)
   except bc.ManifestError:
      data = _load_json(path)
   if not isinstance(data, dict):
      return
   entry_texts = battle_entry_texts()
   for kind in battle.KINDS:
      for e in data.get(kind, []) if isinstance(data.get(kind), list) else []:
         if not isinstance(e, dict):
            continue
         name = e.get("name")
         if isinstance(name, str):
            yield f"battle: {battle.SINGULAR[kind]} {name}", name, False
         for key in entry_texts.get(kind, ()):
            if isinstance(e.get(key), str):
               yield f"battle: {battle.SINGULAR[kind]} {name} {key}", e[key], True
         if kind in BATTLE_TEXT_OBJECTS and isinstance(e.get("texts"), dict):
            for key, v in e["texts"].items():
               if isinstance(v, str):
                  yield f"battle: {battle.SINGULAR[kind]} {name} {key}", v, True
   for kind, word in BATTLE_CONDITION_RECORDS.items():
      for e in data.get(kind, []) if isinstance(data.get(kind), list) else []:
         if not isinstance(e, dict) or not isinstance(e.get("name"), str):
            continue
         yield f"battle: {word} {e['name']}", e["name"], False
         for key, v in (e.get("texts") or {}).items() if isinstance(e.get("texts"), dict) else []:
            if isinstance(v, str):
               yield f"battle: {word} {e['name']} {key}", v, True
   for key, v in (data.get("messages") or {}).items() if isinstance(data.get("messages"), dict) else []:
      if isinstance(v, str):
         yield f"battle: message {key}", v, True
   # Stat labels and the stages' labels are in-game texts too (a stage without a label shows its stat's label, or
   # its name).
   for st in data.get("stats", []) if isinstance(data.get("stats"), list) else []:
      if isinstance(st, dict) and isinstance(st.get("label"), str):
         yield f"battle: stat {st.get('name')} label", st["label"], False
   for st in data.get("stages", []) if isinstance(data.get("stages"), list) else []:
      if not isinstance(st, dict):
         continue
      name = st.get("name", st.get("stat"))
      if isinstance(st.get("label"), str):
         yield f"battle: stage {name} label", st["label"], False
      elif "stat" not in st and isinstance(name, str):
         yield f"battle: stage {name} name", name, False
   # A resource's label is an in-game text (D-25; without one the game shows its name).
   for r in data.get("resources", []) if isinstance(data.get("resources"), list) else []:
      if isinstance(r, dict) and isinstance(r.get("name"), str):
         label = r.get("label", r["name"])
         if isinstance(label, str):
            yield f"battle: resource {r['name']} label", label, False
   doc =Document(data, path, battle.BATTLE_SCHEMA) if data.get("schema") == battle.BATTLE_SCHEMA else None
   for concept, t in (battle.terms(doc).items() if doc is not None else []):
      for form, word in t.items():
         yield f"battle: term {concept} ({form})", word, False


def _location_texts(path: Path) -> Iterator[TextUse]:
   """!Location names of a world.
   @param path  world.json
   @return iterator of TextUse
   """
   data = _load_json(path)
   locs = data.get("locations") if isinstance(data, dict) else None
   for key, loc in (locs.items() if isinstance(locs, dict) else []):
      if isinstance(loc, dict) and isinstance(loc.get("name"), str):
         yield f"world: location {key}", loc["name"], False


def _script_texts(path: Path) -> Iterator[TextUse]:
   """!Inline texts (string literals) of a scripts manifest's sources.
   @param path  scripts.json
   @return iterator of TextUse
   """
   data = _load_json(path)
   sources = data.get("sources") if isinstance(data, dict) else None
   sc = engine.tool("script_compiler")
   for rel in sources if isinstance(sources, list) else []:
      src = path.parent / str(rel)
      try:
         tokens = sc.tokenize(src.read_text(encoding="utf-8"), src.name)
      except (OSError, sc.ScriptError):
         continue   # the script compiler reports it
      for tok in tokens:
         if tok.kind == "string":
            yield f"scripts: {rel} line {tok.line}", tok.text, False


## Readers of the project's game files (project.GAME_FILES keys): key -> function(path) -> TextUse iterator.
READERS = {"assets": _asset_texts, "battle": _battle_texts, "maps": _location_texts, "scripts": _script_texts}


def texts(project: Document) -> list[TextUse]:
   """!Every text of the project the build encodes with its code page: text
   assets, battle names, messages and texts (with the game's terms), location
   names and the scripts' inline texts.
   @param project  project Document
   @return list of (where, text, allows markup)
   """
   from . import project as projects   # core.project imports nothing from here

   out = []
   for key, path in projects.game_files(project).items():
      reader = READERS.get(key)
      if reader is not None and path.is_file():
         out += list(reader(path))
   return out


def missing(project: Document, page: Any = None) -> dict[str, list[str]]:
   """!The characters the project's texts use that its code page lacks.
   @param project  project Document
   @param page     the code page (the project's when None)
   @return {character: [where it is used, ...]}, characters in order of first use
   """
   page = page if page is not None else load(project)
   out: dict[str, list[str]] = {}
   for where, text, markup in texts(project):
      for ch in unmapped(page, plain(text) if markup else text):
         out.setdefault(ch, []).append(where)
   return out


# -- editing a page (inside its Document's edit()) -------------------------------------------------

def parse_code(text: str | int) -> int:
   """!A code from the command line or an editor: a number, written in decimal (128) or hex (0x80).
   @param text  the value
   @return the code
   """
   if isinstance(text, int):
      code = text
   else:
      try:
         code = int(str(text), 0)
      except ValueError:
         raise DocumentError(f"a code is a number such as 0x80 or 128, got {text!r}") from None
   if not 0 <= code <= encoder().MAX_GLYPH_CODE:
      raise DocumentError(f"codes go from 0x00 to 0x{encoder().MAX_GLYPH_CODE:02X}")
   return code


def code_key(code: int) -> str:
   """!How a page's "map" writes a code.
   @param code  the code
   @return e.g. "0x80"
   """
   return f"{encoder().HEX_PREFIX}{code:02X}"


def check(data: dict[str, Any]) -> Any:
   """!Checks page data with the engine's encoder.
   @param data  the parsed capsule.codepage/1 manifest
   @return text_encoder.CodePage
   @throws DocumentError with the encoder's message
   """
   te = encoder()
   try:
      return te.CodePage(data, str(data.get("id", "code page")))
   except te.TextError as e:
      raise DocumentError(str(e)) from None


def _map_code(key: Any) -> int | None:
   """!The code of a "map" key ("0x80" or a number).
   @param key  the key
   @return the code, or None when it is not one
   """
   try:
      return int(key, 0) if isinstance(key, str) else int(key)
   except (TypeError, ValueError):
      return None


def _take_out(data: dict[str, Any], code: int) -> bool:
   """!Removes a code from the page data: its "map" entry, or its place in a
   range (the range splits in two around it).
   @param data  page data (changed in place)
   @param code  the code
   @return True when the code was mapped
   """
   single = data.get("map")
   if isinstance(single, dict):
      for key in [k for k in single if _map_code(k) == code]:
         del single[key]
         return True
   ranges = data.get("ranges") if isinstance(data.get("ranges"), list) else []
   for i, r in enumerate(ranges):
      first = _map_code(r.get("first")) if isinstance(r, dict) else None
      chars = r.get("chars") if isinstance(r, dict) else None
      if first is None or not isinstance(chars, str) or not first <= code < first + len(chars):
         continue
      k = code - first
      parts = []
      if chars[:k]:
         parts.append({"first": code_key(first), "chars": chars[:k]})
      if chars[k + 1:]:
         parts.append({"first": code_key(code + 1), "chars": chars[k + 1:]})
      ranges[i:i + 1] = parts
      return True
   return False


def set_code(page_doc: Document, code: int, char: str) -> None:
   """!Gives a code a character (replacing what it had).
   @param page_doc  code page Document
   @param code      the code (0x00 to 0xF9)
   @param char      the character (one character, with any combining marks)
   @return None
   @throws DocumentError when the page would be invalid (the character mapped elsewhere, space or digits moved)
   """
   code = parse_code(code)
   char = unicodedata.normalize(encoder().NORMAL_FORM, char)
   data = page_doc.data
   _take_out(data, code)
   single = data.setdefault("map", {})
   single[code_key(code)] = char
   data["map"] = dict(sorted(single.items(), key=lambda kv: _map_code(kv[0]) or 0))
   check(data)


def unset_code(page_doc: Document, code: int) -> None:
   """!Leaves a code without a character.
   @param page_doc  code page Document
   @param code      the code
   @return None
   """
   code = parse_code(code)
   if not _take_out(page_doc.data, code):
      raise DocumentError(f"code {code_key(code)} has no character")
   check(page_doc.data)


def set_alias(page_doc: Document, text: str, target: str | None) -> None:
   """!Folds a text the page does not map onto mapped text (None removes the alias).
   @param page_doc  code page Document
   @param text      the folded character(s), e.g. a curly quote
   @param target    what it encodes as (mapped characters), or None
   @return None
   """
   nf = encoder().NORMAL_FORM
   text = unicodedata.normalize(nf, text)
   aliases = page_doc.data.setdefault("aliases", {})
   if target is None:
      if text not in aliases:
         raise DocumentError(f"{text!r} has no alias")
      del aliases[text]
   else:
      aliases[text] = unicodedata.normalize(nf, target)
   check(page_doc.data)


def open_page(project: Document) -> Document:
   """!The project's own code page file, to edit.
   @param project  project Document
   @return code page Document
   @throws DocumentError when the game uses the engine's default page (import_page() gives it its own)
   """
   path = page_path(project)
   if path is None:
      raise DocumentError("the game uses the engine's default code page; give it its own first "
                          "(text codepage import)")
   try:
      return Document.open(path, SCHEMA)
   except (OSError, ValueError) as e:
      raise DocumentError(f"cannot read {path}: {e}") from e


def import_page(project: Document, source: str | Path | None = None, lang: str | None = None,
                replace: bool = False) -> Path:
   """!Gives the game its own code page: copies a page file (the engine's
   default when None) into data/text/LANGUAGE.codepage.json and names it in
   the project's "text" object (call inside project.edit(), then save it).
   @param project  project Document
   @param source   a capsule.codepage/1 file, or None
   @param lang     the language id (default: the page's id)
   @param replace  replace a page the project already names for that language
   @return the new page file
   """
   te = encoder()
   src = Path(source) if source is not None else te.DEFAULT_PATH
   data = _load_json(src)
   if not isinstance(data, dict):
      raise DocumentError(f"cannot read {src} as JSON")
   page = check(data)
   lang = lang or page.id
   text = project.data.setdefault("text", {})
   if not isinstance(text, dict):
      raise DocumentError("the project's \"text\" must be an object")
   pages = text.setdefault("code_pages", {})
   if lang in pages and not replace:
      raise DocumentError(f"the project already has a code page for {lang!r} ({pages[lang]}); replace it to "
                          "import another")
   rel = f"{PAGE_FOLDER}/{lang}{PAGE_SUFFIX}"
   out = game_folder(project) / rel
   data = dict(data)
   data["id"] = lang
   manifest_io.save(out, data)
   pages[lang] = rel
   text["language"] = lang
   return out


def grid(page: Any) -> list[str]:
   """!The page as 16 rows of 16 codes (unmapped codes as "."), for show().
   @param page  text_encoder.CodePage
   @return lines, a header first
   """
   te = encoder()
   lines = ["     " + " ".join(f"{c:X}" for c in range(ROW_CODES))]
   for row in range(0, te.MAX_GLYPH_CODE + 1, ROW_CODES):
      chars = [page.chars.get(row + c, ".") if row + c <= te.MAX_GLYPH_CODE else " " for c in range(ROW_CODES)]
      lines.append(f"{row:02X}   " + " ".join(chars))
   return lines
