"""!An asset manifest's includes and text tables (engine I4: capsule.assets/1 "includes", "text_tables") [S2].

"includes" lists other asset manifests whose palettes and assets join this one; "text_tables" lists text tables
(capsule.texts/1, core.text_tables), each text a text asset. Both are paths relative to the manifest. The engine's
asset_compiler.expand_manifest() is the one authority on them (a cycle, a missing file, a palette defined twice):
every edit here is checked by it (and an include that leads back to the manifest is refused before it is saved).
tables() walks the includes and lists every table the manifest reaches with its language. Engine C10 [S4]: one
manifest may list the tables of several languages (each table's "language"; a table without one is in every
language); the build takes one language (the compiler's --language, else the manifest's "language", else the
tables' only one) and a key it lacks takes the "fallback_language"'s text. The engine's select_language() decides:
language_problem() runs it on the tables' keys (ambiguous, missing or unknown languages), build_language() says
which one a build takes, set_language() changes the manifest's two keys. A game may also keep its other languages
in sibling language folders (text/en/main.json, text/de/main.json: the importer's layout), which translations()
finds; key_matrix() puts a key's tables by language side by side (a key a language lacks is a missing translation,
missing_translations(); fallback_keys() those the fallback fills in); fonts() lists the proportional fonts the
manifest and its tables name. fit_report() compiles the whole manifest with the engine (compile_manifest() with the
game's code page, field placeholders and language) and returns its own fit report, the numbers the build prints.

Qt-free; the Manifest and Text tables panels and `capsule-studio manifest ...` use it.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import engine, paths
from .document import Document, DocumentError

## Manifest keys this module edits, in the engine's order of reading (asset_compiler.expand_manifest()).
LIST_KEYS = ("includes", "text_tables")
## Schema each list's files have.
LIST_SCHEMAS = {"includes": "capsule.assets/1", "text_tables": "capsule.texts/1"}
## A parsed JSON object.
JsonDict = dict[str, Any]
## C10: the manifest keys of the build's language and its fallback.
LANGUAGE_KEYS = ("language", "fallback_language")
## The language label of a table without one (it is in every language).
EVERY_LANGUAGE = ""


def entries(doc: Document, key: str) -> list[str]:
   """!A manifest's includes or text tables.
   @param doc  asset manifest Document
   @param key  "includes" or "text_tables"
   @return the paths as written
   """
   if key not in LIST_KEYS:
      raise DocumentError(f"{key!r} is not one of {', '.join(LIST_KEYS)}")
   value = doc.data.get(key)
   return [str(v) for v in value] if isinstance(value, list) else []


def expanded(doc: Document) -> tuple[JsonDict, list[JsonDict]]:
   """!The manifest with its includes merged and its tables read, by the engine (asset_compiler.expand_manifest()).
   @param doc  asset manifest Document (saved: paths are relative to its folder)
   @return (merged manifest, table texts)
   @throws DocumentError with the compiler's message
   """
   ac = engine.asset_compiler()
   try:
      return ac.expand_manifest(doc.data, doc.base_dir or Path("."))
   except ac.ManifestError as e:
      raise DocumentError(str(e)) from None


def _relative(doc: Document, path: str | Path) -> str:
   """!A path as the manifest writes it: relative to its folder, '/' separators.
   @param doc   asset manifest Document
   @param path  absolute or relative path
   @return the relative path
   """
   p = Path(path)
   if paths.is_absolute_text(str(p)):
      if doc.base_dir is None:
         raise DocumentError("save the manifest first: its paths are relative to its folder")
      return paths.relative(p, doc.base_dir)
   return p.as_posix()


def add_entry(doc: Document, key: str, path: str | Path) -> str:
   """!Adds an include or a text table (call inside Document.edit()); the engine then reads the whole manifest.
   @param doc   asset manifest Document
   @param key   "includes" or "text_tables"
   @param path  the file (relative to the manifest, or absolute)
   @return the path as written
   @throws DocumentError when it is listed already, is not of the list's schema, or the engine refuses the result
   """
   rel = _relative(doc, path)
   have = entries(doc, key)
   if rel in have:
      raise DocumentError(f"{rel} is in {key} already")
   full = (doc.base_dir or Path(".")) / rel
   try:
      schema = json.loads(full.read_text(encoding="utf-8")).get("schema")
   except (OSError, ValueError, AttributeError) as e:
      raise DocumentError(f"cannot read {rel}: {e}") from None
   if schema != LIST_SCHEMAS[key]:
      raise DocumentError(f"{rel} is not a {LIST_SCHEMAS[key]} file")
   if key == "includes" and doc.path is not None and _reaches(full.resolve(), doc.path, set()):
      raise DocumentError(f"includes: {rel} includes this manifest (a cycle)")
   doc.data[key] = have + [rel]
   expanded(doc)
   return rel


def _reaches(path: Path, target: Path, seen: set[Path]) -> bool:
   """!Whether a manifest is, or includes (through its includes on disk), another.
   @param path    the manifest
   @param target  the one looked for
   @param seen    manifests visited
   @return True when it leads to it
   """
   if path == target:
      return True
   if path in seen:
      return False
   seen.add(path)
   try:
      data = json.loads(path.read_text(encoding="utf-8"))
   except (OSError, ValueError):
      return False
   return any(_reaches((path.parent / str(r)).resolve(), target, seen)
              for r in (data.get("includes", []) if isinstance(data, dict) else []) or [])


def remove_entry(doc: Document, key: str, path: str) -> None:
   """!Removes an include or a text table (call inside Document.edit()); the files stay.
   @param doc   asset manifest Document
   @param key   "includes" or "text_tables"
   @param path  the path as written
   @return None
   """
   have = entries(doc, key)
   if path not in have:
      raise DocumentError(f"{path} is not in {key}")
   have.remove(path)
   if have:
      doc.data[key] = have
   else:
      doc.data.pop(key, None)


def move_entry(doc: Document, key: str, path: str, step: int) -> None:
   """!Moves an include or a table up or down (call inside Document.edit(); includes merge in order).
   @param doc   asset manifest Document
   @param key   "includes" or "text_tables"
   @param path  the path as written
   @param step  -1 up, 1 down
   @return None
   """
   have = entries(doc, key)
   if path not in have:
      raise DocumentError(f"{path} is not in {key}")
   i = have.index(path)
   j = min(max(i + step, 0), len(have) - 1)
   have.insert(j, have.pop(i))
   doc.data[key] = have


@dataclass
class TableRef:
   """!A text table a manifest reaches."""

   ## The table's file (absolute).
   path: Path
   ## Its path from the top manifest's folder (for display).
   label: str
   ## Its language ("" when it cannot be read).
   language: str
   ## The manifest that lists it (absolute).
   owner: Path
   ## Whether the manifest lists it (False: another language's table of the same name, translations()).
   listed: bool = True


def tables(doc: Document) -> list[TableRef]:
   """!Every text table the manifest reaches: its own, then its includes' (in order; a cycle is not followed).
   @param doc  asset manifest Document (saved)
   @return the tables
   """
   if doc.base_dir is None or doc.path is None:
      return []
   out: list[TableRef] = []
   seen: set[Path] = set()

   def walk(data: JsonDict, owner: Path) -> None:
      """!Adds a manifest's tables, then walks its includes.
      @param data   the manifest
      @param owner  its file
      """
      for rel in data.get("text_tables", []) or []:
         path = (owner.parent / str(rel)).resolve()
         try:
            lang = str(json.loads(path.read_text(encoding="utf-8")).get("language", ""))
         except (OSError, ValueError, AttributeError):
            lang = ""
         # The label from the resolved folder: the table is resolved (a linked folder would climb out and back).
         out.append(TableRef(path, paths.relative(path, doc.base_dir, label=True), lang, owner))
      for rel in data.get("includes", []) or []:
         path = (owner.parent / str(rel)).resolve()
         if path in seen:
            continue
         seen.add(path)
         try:
            inner = json.loads(path.read_text(encoding="utf-8"))
         except (OSError, ValueError):
            continue
         if isinstance(inner, dict):
            walk(inner, path)

   seen.add(doc.path)
   walk(doc.data, doc.path)
   return out


def translations(ref: TableRef, base: Path) -> list[TableRef]:
   """!A table's other languages: the tables of the same file name in its folder's sibling folders
   (text/LANGUAGE/NAME.json) whose language differs.
   @param ref   the table
   @param base  the top manifest's folder (for labels)
   @return TableRef list (listed False)
   """
   out = []
   for candidate in sorted(ref.path.parent.parent.glob(f"*/{ref.path.name}")):
      candidate = candidate.resolve()
      if candidate == ref.path:
         continue
      try:
         data = json.loads(candidate.read_text(encoding="utf-8"))
      except (OSError, ValueError):
         continue
      if not isinstance(data, dict) or data.get("schema") != LIST_SCHEMAS["text_tables"]:
         continue
      lang = str(data.get("language", ""))
      if lang and lang != ref.language:
         out.append(TableRef(candidate, paths.relative(candidate, base, label=True), lang, ref.owner, False))
   return out


def table_set(doc: Document) -> list[TableRef]:
   """!The tables the manifest reaches, then their other languages' tables (translations()), each once.
   @param doc  asset manifest Document (saved)
   @return TableRef list
   """
   refs = tables(doc)
   seen = {r.path for r in refs}
   out = list(refs)
   for r in refs:
      for t in translations(r, doc.base_dir or Path(".")):
         if t.path not in seen:
            seen.add(t.path)
            out.append(t)
   return out


def key_matrix(docs: dict[Path, Document]) -> dict[str, dict[str, Path]]:
   """!Each text key with the table holding it per language (EVERY_LANGUAGE: a table without a language).
   @param docs  the tables' Documents by path
   @return key -> {language: table path}
   """
   out: dict[str, dict[str, Path]] = {}
   for path, d in docs.items():
      lang = str(d.data.get("language", EVERY_LANGUAGE))
      for key in (d.data.get("texts") or {}):
         out.setdefault(key, {})[lang] = path
   return out


def missing_translations(docs: dict[Path, Document]) -> dict[str, list[str]]:
   """!The keys a language lacks that another has (a key of a table without a language is in every language).
   @param docs  the tables' Documents by path
   @return language -> keys (sorted), only languages with some missing
   """
   matrix = key_matrix(docs)
   langs = sorted({str(d.data.get("language", EVERY_LANGUAGE)) for d in docs.values()} - {EVERY_LANGUAGE})
   out = {}
   for lang in langs:
      missing = sorted(k for k, by in matrix.items() if lang not in by and EVERY_LANGUAGE not in by)
      if missing:
         out[lang] = missing
   return out


def fallback_keys(docs: dict[Path, Document], language: str, fallback: str | None) -> list[str]:
   """!C10: the keys a build in a language takes from its fallback language (select_language()'s rule).
   @param docs      the tables' Documents by path
   @param language  the build's language
   @param fallback  the manifest's fallback_language, or None
   @return keys (sorted)
   """
   if not fallback or fallback == language:
      return []
   return sorted(k for k, by in key_matrix(docs).items()
                 if fallback in by and language not in by and EVERY_LANGUAGE not in by)


def language_setting(doc: Document, key: str) -> str | None:
   """!C10: the manifest's build language or fallback.
   @param doc  asset manifest Document
   @param key  "language" or "fallback_language"
   @return the language, or None
   """
   if key not in LANGUAGE_KEYS:
      raise DocumentError(f"{key!r} is not one of {', '.join(LANGUAGE_KEYS)}")
   v = doc.data.get(key)
   return str(v) if isinstance(v, str) and v else None


def _table_texts(doc: Document, docs: dict[Path, Document] | None = None) -> list[JsonDict]:
   """!The keys of the tables the manifest lists, as the engine's select_language() reads them ({key, language}).
   @param doc   asset manifest Document (saved)
   @param docs  open table Documents by path (an editor's unsaved tables), or None (read from disk)
   @return records
   """
   out: list[JsonDict] = []
   for ref in tables(doc):
      data: Any = docs[ref.path].data if docs and ref.path in docs else None
      if data is None:
         try:
            data = json.loads(ref.path.read_text(encoding="utf-8"))
         except (OSError, ValueError):
            continue
      if not isinstance(data, dict):
         continue
      lang = data.get("language")
      out += [{"key": k, "language": lang} for k in (data.get("texts") or {})]
   return out


def languages(doc: Document, docs: dict[Path, Document] | None = None) -> list[str]:
   """!C10: the languages of the tables the manifest lists (through its includes).
   @param doc   asset manifest Document (saved)
   @param docs  open table Documents by path, or None
   @return languages, sorted
   """
   return sorted({str(t["language"]) for t in _table_texts(doc, docs) if t.get("language") is not None})


def language_problem(doc: Document, language: str | None = None, docs: dict[Path, Document] | None = None,
                     settings: Mapping[str, Any] | None = None) -> str | None:
   """!C10: what the engine says about the manifest's languages (asset_compiler.select_language() on its tables'
   keys): several languages and none named, a language no table has, a fallback no table has.
   @param doc       asset manifest Document (saved)
   @param language  the build's --language, or None (the manifest's)
   @param docs      open table Documents by path, or None
   @param settings  the manifest's language keys to check instead of its own, or None
   @return the compiler's message, or None
   """
   ac = engine.asset_compiler()
   if not hasattr(ac, "select_language"):
      return None   # an engine before C10: one language per manifest
   manifest = {k: v for k, v in (settings if settings is not None else doc.data).items() if k in LANGUAGE_KEYS}
   try:
      ac.select_language(_table_texts(doc, docs), manifest, language)
   except ac.ManifestError as e:
      return str(e)
   return None


def build_language(doc: Document, language: str | None = None, docs: dict[Path, Document] | None = None) -> str | None:
   """!C10: the language a build of the manifest takes (select_language()'s choice).
   @param doc       asset manifest Document (saved)
   @param language  the build's --language, or None
   @param docs      open table Documents by path, or None
   @return the language, or None (no table has one, or the choice is refused: language_problem())
   """
   langs = languages(doc, docs)
   chosen = language or language_setting(doc, LANGUAGE_KEYS[0])
   if chosen is None and len(langs) == 1:
      chosen = langs[0]
   return chosen if chosen in langs else None


def set_language(doc: Document, key: str, value: str | None, docs: dict[Path, Document] | None = None) -> None:
   """!C10: sets the manifest's build language or fallback (call inside Document.edit()); the engine's rule must
   accept the result (language_problem()).
   @param doc    asset manifest Document (saved)
   @param key    "language" or "fallback_language"
   @param value  a language of the manifest's tables, or None to leave the key out
   @param docs   open table Documents by path, or None
   @return None
   @throws DocumentError when the engine refuses it
   """
   language_setting(doc, key)
   wanted = {k: doc.data[k] for k in LANGUAGE_KEYS if k in doc.data}
   if value:
      wanted[key] = str(value)
   else:
      wanted.pop(key, None)
   if value:
      problem = language_problem(doc, None, docs, wanted)
      if problem is not None:
         raise DocumentError(problem)
   if value:
      doc.data[key] = str(value)
   else:
      doc.data.pop(key, None)


def fonts(doc: Document) -> list[tuple[str, Path]]:
   """!The proportional fonts the manifest reaches: its font assets (and its includes'), then its tables' fonts.
   @param doc  asset manifest Document (saved)
   @return (label, absolute path) pairs without repeats: an asset's key, or "table font NAME"
   """
   out: list[tuple[str, Path]] = []
   seen: set[Path] = set()
   if doc.base_dir is None:
      return out
   try:
      merged, _texts = expanded(doc)
   except DocumentError:
      merged = doc.data
   for a in merged.get("assets", []):
      if a.get("kind") == "font" and isinstance(a.get("font"), str):
         path = (doc.base_dir / a["font"]).resolve()
         if path not in seen:
            seen.add(path)
            out.append((str(a.get("key")), path))
   for t in tables(doc):
      try:
         data = json.loads(t.path.read_text(encoding="utf-8"))
      except (OSError, ValueError):
         continue
      for name, rel in (data.get("fonts") or {}).items():
         path = (t.path.parent / str(rel)).resolve()
         if path not in seen:
            seen.add(path)
            out.append((f"table font {name}", path))
   return out


def fit_report(doc: Document, page: Any, field: Any, language: str | None = None) -> JsonDict:
   """!The engine's own check of the whole manifest (asset_compiler.compile_manifest(): includes, tables, fonts) and
   its fit report.
   @param doc       asset manifest Document (saved)
   @param page      the game's code page
   @param field     the game's field placeholders, or None
   @param language  C10: the build's language (the compiler's --language), or None (the manifest's)
   @return {"checked", "over", "with_placeholders", "lines", "assets"} (assets: the entries compiled)
   @throws DocumentError with the compiler's message
   """
   ac = engine.asset_compiler()
   try:
      extra = {"language": language} if language else {}   # C10
      entries_, *_rest = ac.compile_manifest(doc.data, doc.base_dir, None, codepage=page, field=field, **extra)
   except ac.ManifestError as e:
      raise DocumentError(str(e)) from None
   fit = dict(ac.compile_manifest.fit)
   fit["assets"] = len(entries_)
   return fit
