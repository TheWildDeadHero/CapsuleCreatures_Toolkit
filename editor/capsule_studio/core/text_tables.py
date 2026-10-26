"""!Text tables (engine I4, D-8 C-3: capsule.texts/1) for the text table editor [S2].

A table is a Document (schema capsule.texts/1, opened keeping its file's json layout, so a table saved unchanged
stays byte-identical): a language, a box ({"font", "width", "lines"}: the box its authored texts must fit), its
fonts (name -> a capsule.font/2 file) and its texts (key -> a string or {"text", "wrap", "font", ...}). An asset
manifest names its tables in "text_tables" and other manifests in "includes" (core.asset_tables).

The engine's tools/asset_compiler.py is the one authority: every edit is checked by its load_text_table() on the
Document's data (a fonts.MemoryFile), and check_text() fits a text with its own rule: the text encoded by
encode_text() with the game's field placeholders, its glyphs against the font (glyphs_of()), each authored line
measured by measure_lines() ("wrap": "original": a line wider than the box is a fit warning, a line with a
placeholder that counts nothing is marked), automatic texts broken by wrap_codes() ("wrap": "auto"). The code page
and the field placeholders come from the game (TextContext.for_manifest()).

Control codes: controls() lists the generic controls (text_encoder.CONTROL_CODES: name, byte, argument widths;
their descriptions from capsule/text/encode.h) and the two markup controls (prompt, page); markup() writes one.

Qt-free; the text table panel (ui/editors/text_tables.py) and `capsule-studio text-table ...` use it.
"""
from __future__ import annotations

import dataclasses
import re
import types
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import codepage, engine
from .document import Document, DocumentError
from .fonts import MemoryFile

## Schema of a text table (the engine's asset_compiler.TEXT_TABLE_SCHEMA; a test keeps them equal).
SCHEMA = "capsule.texts/1"
## A parsed JSON object.
JsonDict = dict[str, Any]
## Header of the engine's control list (its comments describe each control).
ENCODE_HEADER = "capsule/text/encode.h"
## A control's line in that header: its enum name, a comma, the doc comment with its byte, arguments and description.
CONTROL_LINE = re.compile(r"^\s*(?P<name>\w+),\s*///<\s*(?P<code>[0-9A-Fa-f]{2})\b[^:]*:\s*(?P<doc>.*?)\s*$")
## Base of the header's control bytes.
HEX_BASE = 16
## The markup controls of the text encoder (CONTROLS) with what they do.
MARKUP_CONTROLS = {"prompt": "wait for a button, then go on", "page": "wait for a button, then a new page"}
## The name of the generic control that ends an authored line like a newline (text_encoder.CONTROL_CODES).
SCROLL_CONTROL = "scroll"
## Folder depths below an asset manifest's parent searched for the scripts manifest naming it (world/scripts/).
SCRIPTS_SEARCH_DEPTH = 3
## File name of a scripts manifest.
SCRIPTS_FILE = "scripts.json"
## Schema of an asset manifest.
ASSETS_SCHEMA = "capsule.assets/1"
## Suffix of a code page file.
CODEPAGE_SUFFIX = ".codepage.json"
## S4: a table's language code (set_language()).
LANGUAGE_CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


def compiler() -> types.ModuleType:
   """!The engine's asset compiler.
   @return module
   """
   return engine.asset_compiler()


def encoder() -> types.ModuleType:
   """!The engine's text encoder.
   @return module
   """
   return engine.tool("text_encoder")


def wrap_modes() -> list[str]:
   """!The wrap modes of a table text (asset_compiler.WRAP_MODES; the last is the default).
   @return modes
   """
   return list(compiler().WRAP_MODES)


def default_wrap() -> str:
   """!The wrap mode of a text that names none.
   @return mode
   """
   return wrap_modes()[-1]


# -- the game's text settings -------------------------------------------------------------------------------------

@dataclass
class TextContext:
   """!What texts are encoded and fitted with: the code page, the field placeholders, and the fonts compiled so far."""

   ## The code page (text_encoder.CodePage).
   page: Any
   ## The field placeholders (script_compiler.FieldPlaceholders), or None (braces are plain characters).
   field: Any = None
   ## The scripts manifest they came from, or None.
   scripts: Path | None = None
   ## The code page's file, or None (the engine's default page or a project's).
   page_file: Path | None = None
   ## Compiled fonts by absolute path.
   fonts: dict[Path, JsonDict] = dataclasses.field(default_factory=dict)
   ## Font Documents being edited, by absolute path: their data is used instead of the file.
   open_fonts: dict[Path, Document] = dataclasses.field(default_factory=dict)

   @classmethod
   def for_manifest(cls, manifest: Path | None, scripts: Path | None = None, page_file: Path | None = None
                    ) -> TextContext:
      """!The text settings of the game an asset manifest belongs to: the code page of its project
      (core.codepage), else the one code page file beside the manifest (an importer's output: `*.codepage.json`);
      the field placeholders of the scripts manifest naming it (find_scripts()).
      @param manifest   the asset manifest (or a table), or None
      @param scripts    the scripts manifest, or None to find it
      @param page_file  the code page file, or None to find it
      @return TextContext
      @throws DocumentError when a file named or found is malformed
      """
      te = encoder()
      page = None
      if page_file is None and manifest is not None:
         page_file = find_codepage(manifest)
      if page_file is not None:
         try:
            page = te.CodePage.load(page_file)
         except te.TextError as e:
            raise DocumentError(str(e)) from None
      elif manifest is not None:
         page = codepage.for_file(manifest)
      page = page if page is not None else te.DEFAULT
      if scripts is None and manifest is not None:
         # a table or a font: the scripts manifest names the asset manifest listing it
         scripts = find_scripts(owner_manifest(manifest) or manifest)
      field_ = None
      if scripts is not None:
         sc = engine.tool("script_compiler")
         try:
            field_ = sc.load_placeholders(scripts, page)
         except sc.ScriptError as e:
            raise DocumentError(f"{scripts.name}: {e}") from None
      return cls(page, field_, scripts, page_file)

   def font(self, path: Path) -> JsonDict:
      """!A font compiled for the code page (an open font Document's data, else the file; cached).
      @param path  the .font.json
      @return compile_proportional()'s result
      @throws DocumentError with the compiler's message
      """
      from . import fonts
      page = self.page   # a local alias (Doxygen 1.12 reads a dataclass field used in a method as a new member)
      path = Path(path).resolve()
      doc = self.open_fonts.get(path)
      if doc is not None:
         return fonts.compile_font(doc, page)
      if path not in self.fonts:
         te = encoder()
         try:
            self.fonts[path] = fonts.compiler().compile_proportional(path, page)
         except te.TextError as e:
            raise DocumentError(str(e)) from None
      return self.fonts[path]

   def encode(self, text: str, where: str) -> list[int]:
      """!A table text's codes (asset_compiler.encode_text(): field text with the placeholders, else plain).
      @param text   the text
      @param where  location for the message
      @return codes ending with CODE_END
      @throws DocumentError when it does not encode
      """
      ac = compiler()
      try:
         page, placeholders = self.page, self.field   # local aliases (see font())
         return ac.encode_text(text, where, page, placeholders)
      except ac.ManifestError as e:
         raise DocumentError(str(e)) from None

   def placeholder_codes(self) -> dict[int, list[int]]:
      """!What a preview shows for each placeholder: a term's text, else its name in capitals.
      @return argument byte -> glyph codes
      """
      from .text_render import stand_in
      out: dict[int, list[int]] = {}
      if self.field is None:
         return out
      for name, arg in self.field.codes.items():
         kind, value, extra = self.field.bindings.get(name, ("", None, {}))
         if kind == "term":
            out[arg] = self.field.term_codes(name, value, extra.get("form", "one"))[:-1]
         else:
            out[arg] = stand_in(name, self.page)
      return out


def find_codepage(manifest: Path) -> Path | None:
   """!The code page file of an imported game's text: the one `*.codepage.json` in the manifest's folder or its
   parent (none when the folder has none, or several and none in the project).
   @param manifest  an asset manifest or a table
   @return the file, or None (the project's page, core.codepage)
   """
   manifest = Path(manifest).resolve()
   if codepage.find_project(manifest) is not None:
      return None
   for folder in (manifest.parent, manifest.parent.parent):
      found = sorted(folder.glob("*" + CODEPAGE_SUFFIX))
      if len(found) == 1:
         return found[0]
   return None


def owner_manifest(path: Path) -> Path | None:
   """!The asset manifest that lists a text table (or names a font) in its folder or the two above it.
   @param path  a table, a font or an asset manifest
   @return the manifest (the path itself when it is one), or None
   """
   import json
   path = Path(path).resolve()
   for folder in (path.parent, path.parent.parent, path.parent.parent.parent):
      for candidate in sorted(folder.glob("*.json")):
         try:
            text = candidate.read_text(encoding="utf-8")
            # only asset manifests are parsed (a folder of tables is read, not parsed)
            data = json.loads(text) if ASSETS_SCHEMA in text else None
         except (OSError, ValueError):
            continue
         if not isinstance(data, dict) or data.get("schema") != ASSETS_SCHEMA:
            continue
         if candidate.resolve() == path:
            return path
         listed = [(candidate.parent / str(r)).resolve() for r in data.get("text_tables", []) or []]
         listed += [(candidate.parent / str(a.get("font"))).resolve() for a in data.get("assets", [])
                    if isinstance(a, dict) and a.get("kind") == "font" and a.get("font")]
         if path in listed:
            return candidate.resolve()
   return None


def find_scripts(manifest: Path) -> Path | None:
   """!The scripts manifest whose "assets" names an asset manifest (its field placeholders encode the texts): the
   project's, else a scripts.json beside it or up to SCRIPTS_SEARCH_DEPTH folders below its parent.
   @param manifest  the asset manifest
   @return the scripts manifest, or None
   """
   from . import project as project_mod
   manifest = Path(manifest).resolve()
   found = codepage.find_project(manifest)
   if found is not None:
      try:
         scripts = project_mod.game_files(project_mod.open_project(found)).get("scripts")
      except (DocumentError, OSError, ValueError):
         scripts = None
      if scripts is not None and Path(scripts).is_file():
         return Path(scripts)
   root = manifest.parent.parent
   patterns = [SCRIPTS_FILE] + ["/".join(["*"] * depth + [SCRIPTS_FILE]) for depth in range(1, SCRIPTS_SEARCH_DEPTH)]
   for folder in (manifest.parent, root):
      for pattern in patterns:
         for candidate in sorted(folder.glob(pattern)):
            if _names_assets(candidate, manifest):
               return candidate
   return None


def _names_assets(scripts: Path, manifest: Path) -> bool:
   """!Whether a scripts manifest names an asset manifest.
   @param scripts   the scripts manifest
   @param manifest  the asset manifest (absolute)
   @return True when its "assets" resolves to it
   """
   import json
   try:
      data = json.loads(scripts.read_text(encoding="utf-8"))
   except (OSError, ValueError):
      return False
   rel = data.get("assets") if isinstance(data, dict) else None
   return isinstance(rel, str) and (scripts.parent / rel).resolve() == manifest


# -- tables --------------------------------------------------------------------------------------------------------

def open_table(path: str | Path) -> Document:
   """!Opens a text table.
   @param path  the table
   @return Document (its json layout kept on save)
   @throws DocumentError when it is not a capsule.texts/1 file
   """
   try:
      return Document.open(path, SCHEMA, keep_layout=True)
   except (OSError, ValueError) as e:
      raise DocumentError(f"cannot read {path}: {e}") from e


def table_texts(doc: Document) -> list[JsonDict]:
   """!The table's texts as the engine reads them (asset_compiler.load_text_table()).
   @param doc  table Document
   @return [{"key", "text", "wrap", "font", "box", "fonts", "table"}]
   @throws DocumentError with the compiler's message when the table is malformed
   """
   ac = compiler()
   try:
      return ac.load_text_table(MemoryFile(doc.data, doc.path))
   except ac.ManifestError as e:
      raise DocumentError(str(e)) from None


@dataclass
class TextRow:
   """!One text of a table."""

   ## Its key.
   key: str
   ## The text (markup).
   text: str
   ## Its wrap mode.
   wrap: str
   ## Its font's name, or None (the box's).
   font: str | None
   ## Whether the entry names its wrap mode or font itself.
   explicit: bool


def _row(key: str, value: Any, default: str) -> TextRow | None:
   """!A table entry as a TextRow.
   @param key      its key
   @param value    a string or {"text", ...}
   @param default  the default wrap mode
   @return TextRow, or None for a malformed entry (the engine's check names it)
   """
   if isinstance(value, str):
      return TextRow(key, value, default, None, False)
   if isinstance(value, dict):
      return TextRow(key, str(value.get("text", "")), str(value.get("wrap", default)), value.get("font"),
                     "wrap" in value or "font" in value)
   return None


def rows(doc: Document) -> list[TextRow]:
   """!The table's texts in file order.
   @param doc  table Document
   @return rows
   """
   default = default_wrap()
   out = [_row(key, value, default) for key, value in (doc.data.get("texts") or {}).items()]
   return [r for r in out if r is not None]


def entry(doc: Document, key: str) -> TextRow:
   """!One text.
   @param doc  table Document
   @param key  its key
   @return TextRow
   @throws DocumentError when the table has none
   """
   texts = doc.data.get("texts") or {}
   r = _row(key, texts[key], default_wrap()) if key in texts else None
   if r is None:
      raise DocumentError(f"the table has no text {key!r}")
   return r


def box(doc: Document) -> JsonDict:
   """!The table's box (the authored texts' fit box).
   @param doc  table Document
   @return {"font", "width", "lines"} (missing keys absent; {} without a box)
   """
   b = doc.data.get("box")
   return dict(b) if isinstance(b, dict) else {}


def font_path(doc: Document, name: str | None) -> Path | None:
   """!The file of one of the table's fonts.
   @param doc   table Document
   @param name  the font's name, or None for the box's
   @return the absolute path, or None (no such font, or the table is unsaved)
   """
   name = name if name is not None else box(doc).get("font")
   rel = (doc.data.get("fonts") or {}).get(name) if name is not None else None
   if not isinstance(rel, str) or doc.path is None:
      return None
   return (doc.path.parent / rel).resolve()


def _checked(doc: Document) -> None:
   """!Checks the table with the engine after an edit (a refused edit is rolled back by Document.edit()).
   @param doc  table Document
   @return None
   """
   table_texts(doc)


def _key_check(key: str) -> None:
   """!Refuses a key the engine cannot hash (sequence_compiler.asset_key()).
   @param key  the key
   @return None
   """
   sc = engine.tool("sequence_compiler")
   try:
      sc.asset_key(key)
   except sc.ManifestError as e:
      raise DocumentError(str(e)) from None


def set_text(doc: Document, key: str, text: str) -> None:
   """!Changes a text (call inside Document.edit()); a plain string entry stays one.
   @param doc   table Document
   @param key   its key
   @param text  the new text
   @return None
   """
   texts = doc.data.get("texts") or {}
   if key not in texts:
      raise DocumentError(f"the table has no text {key!r}")
   if isinstance(texts[key], dict):
      texts[key]["text"] = text
   else:
      texts[key] = text
   _checked(doc)


def set_wrap(doc: Document, key: str, wrap: str) -> None:
   """!Sets a text's wrap mode (call inside Document.edit()): "original" keeps its authored breaks and is checked
   against the box, "auto" is broken to the box at spaces.
   @param doc   table Document
   @param key   its key
   @param wrap  one of wrap_modes()
   @return None
   """
   if wrap not in wrap_modes():
      raise DocumentError(f"wrap is one of {', '.join(wrap_modes())}")
   texts = doc.data.get("texts") or {}
   if key not in texts:
      raise DocumentError(f"the table has no text {key!r}")
   if isinstance(texts[key], str):
      if wrap == default_wrap():
         return
      texts[key] = {"text": texts[key]}
   texts[key]["wrap"] = wrap
   _checked(doc)


def set_text_font(doc: Document, key: str, font: str | None) -> None:
   """!Sets the font a text is fitted in (call inside Document.edit()).
   @param doc   table Document
   @param key   its key
   @param font  a name of the table's fonts, or None for the box's
   @return None
   """
   texts = doc.data.get("texts") or {}
   if key not in texts:
      raise DocumentError(f"the table has no text {key!r}")
   if isinstance(texts[key], str):
      if font is None:
         return
      texts[key] = {"text": texts[key]}
   if font is None:
      texts[key].pop("font", None)
   else:
      texts[key]["font"] = font
   _checked(doc)


def add_text(doc: Document, key: str, text: str = "", wrap: str | None = None, keys: Iterable[str] = ()) -> None:
   """!Adds a text (call inside Document.edit()).
   @param doc   table Document
   @param key   a new key (text:NAME)
   @param text  its text
   @param wrap  its wrap mode, or None for the default
   @param keys  the keys of the other tables of the manifest (a key is one asset of the whole manifest)
   @return None
   """
   texts = doc.data.setdefault("texts", {})
   _key_check(key)
   if key in texts or key in set(keys):
      raise DocumentError(f"there is a text {key!r} already")
   texts[key] = text if wrap is None or wrap == default_wrap() else {"text": text, "wrap": wrap}
   _checked(doc)


def remove_text(doc: Document, key: str) -> None:
   """!Removes a text (call inside Document.edit()).
   @param doc  table Document
   @param key  its key
   @return None
   """
   texts = doc.data.get("texts") or {}
   if key not in texts:
      raise DocumentError(f"the table has no text {key!r}")
   del texts[key]


def rename_text(doc: Document, old: str, new: str, keys: Iterable[str] = ()) -> None:
   """!Renames a text, keeping its place (call inside Document.edit()).
   @param doc   table Document
   @param old   its key
   @param new   the new key
   @param keys  the keys of the other tables
   @return None
   """
   texts = doc.data.get("texts") or {}
   if old not in texts:
      raise DocumentError(f"the table has no text {old!r}")
   _key_check(new)
   if new != old and (new in texts or new in set(keys)):
      raise DocumentError(f"there is a text {new!r} already")
   doc.data["texts"] = {(new if k == old else k): v for k, v in texts.items()}


def set_box(doc: Document, font: str | None, width: int | None, lines: int | None) -> None:
   """!Sets the table's box (call inside Document.edit()); a None value leaves that key out.
   @param doc    table Document
   @param font   the box font (a name of the table's fonts)
   @param width  pixels a line may take
   @param lines  lines per page (automatic texts)
   @return None
   """
   b = {k: v for k, v in (("font", font), ("width", width), ("lines", lines)) if v is not None}
   for k in ("width", "lines"):
      if k in b and (isinstance(b[k], bool) or not isinstance(b[k], int) or b[k] < 0):
         raise DocumentError(f"the box's {k} is a number of pixels or lines")
   if b:
      doc.data["box"] = b
   else:
      doc.data.pop("box", None)
   _checked(doc)


def set_language(doc: Document, language: str | None) -> None:
   """!S4 (engine C10): sets the table's language (call inside Document.edit()); None leaves it out (the table is
   then in every language of its manifest).
   @param doc       table Document
   @param language  a language code (letters, digits, '-' or '_'), or None
   @return None
   """
   if language:
      if not LANGUAGE_CODE.fullmatch(str(language)):
         raise DocumentError(f"{language!r} is not a language code (letters, digits, - or _)")
      doc.data["language"] = str(language)
   else:
      doc.data.pop("language", None)
   _checked(doc)


def set_font_file(doc: Document, name: str, rel: str | None) -> None:
   """!Adds, changes or removes one of the table's fonts (call inside Document.edit()).
   @param doc   table Document
   @param name  the font's name
   @param rel   its file relative to the table, or None to remove it
   @return None
   """
   fonts = doc.data.setdefault("fonts", {})
   if rel is None:
      fonts.pop(name, None)
   else:
      fonts[name] = Path(rel).as_posix()
   _checked(doc)


# -- fit -------------------------------------------------------------------------------------------------------------

@dataclass
class LineFit:
   """!One authored line of a text in its box."""

   ## Its number, from 1.
   number: int
   ## Its width in the font, pixels (its placeholders counted by their terms, others nothing).
   width: int
   ## The box width.
   box: int
   ## It has a placeholder that counts nothing (the game's text may be longer).
   unmeasured: bool
   ## Its text, when the authored lines line up with the measured ones ("" otherwise).
   text: str = ""

   @property
   def over(self) -> bool:
      """!Whether it is wider than the box.
      @return True when it does not fit
      """
      return self.width > self.box


@dataclass
class TextFit:
   """!A text checked against its table's box (the engine's rule)."""

   ## Its key.
   key: str
   ## Why it does not compile (encoding, a glyph the font lacks, the font), or None.
   error: str | None = None
   ## Its codes (wrapped for "auto" texts), [] when it does not encode.
   codes: list[int] = dataclasses.field(default_factory=list)
   ## The authored lines measured ("original" texts with a box and a font), [] otherwise.
   lines: list[LineFit] = dataclasses.field(default_factory=list)
   ## The box width, or 0 (no box: nothing is fitted).
   box_width: int = 0
   ## The font's file, or None.
   font: Path | None = None

   @property
   def over(self) -> list[LineFit]:
      """!The lines wider than the box.
      @return lines
      """
      return [line for line in self.lines if line.over]


def authored_lines(text: str) -> list[str]:
   """!An authored text's lines as measure_lines() counts them (they end at newlines, {page}, {prompt} and the
   scroll control).
   @param text  the markup
   @return the lines
   """
   breaks = ["\n"] + ["{" + name + "}" for name in list(MARKUP_CONTROLS) + [SCROLL_CONTROL]]
   return re.split("|".join(re.escape(b) for b in breaks), text)


def check_text(ctx: TextContext, doc: Document, key: str, row: TextRow | None = None) -> TextFit:
   """!Fits one text of a table into its box with the engine's rule (asset_compiler.compile_table_texts(): encode,
   the font's glyphs, measure_lines() for an authored text, wrap_codes() for an automatic one).
   @param ctx  the game's text settings
   @param doc  table Document
   @param key  the text
   @param row  its TextRow when the caller has it, or None
   @return TextFit
   """
   ac = compiler()
   r = row if row is not None else entry(doc, key)
   out = TextFit(key)
   where = f"{doc.path.name if doc.path else 'table'}: {key}"
   try:
      codes = ctx.encode(r.text, where)
   except DocumentError as e:
      out.error = str(e)
      return out
   out.codes = codes
   b = box(doc)
   font_name = r.font if r.font is not None else b.get("font")
   path = font_path(doc, font_name)
   if not b or font_name is None or path is None:
      return out
   out.font = path
   try:
      font = ctx.font(path)
   except DocumentError as e:
      out.error = f"{where}: {e}"
      return out
   missing = sorted(set(ac.glyphs_of(codes)) - font["codes"])
   if missing:
      out.error = (f"{where}: the font {font_name!r} has no glyph for "
                   f"{', '.join(ctx.page.decode([c]) or f'0x{c:02X}' for c in missing)}")
      return out
   width = int(b.get("width", 0))
   out.box_width = width
   if width <= 0:
      return out
   if r.wrap == "auto":
      out.codes = ac.wrap_codes(codes, font, width, int(b.get("lines", ac.DEFAULT_BOX_LINES)))
      return out
   measured = ac.measure_lines(codes, font, ctx.field)
   texts = authored_lines(r.text)
   texts = texts if len(texts) == len(measured) else [""] * len(measured)
   out.lines = [LineFit(n + 1, w, width, unmeasured, texts[n]) for n, (w, unmeasured) in enumerate(measured)]
   return out


@dataclass
class TableFit:
   """!A table's texts against its box (the numbers the build's fit report counts)."""

   ## Texts checked against the box (authored ones with a box width).
   checked: int = 0
   ## Lines wider than the box.
   over: int = 0
   ## Lines with a placeholder measured without it.
   with_placeholders: int = 0
   ## The texts that do not fit or do not compile.
   problems: list[TextFit] = dataclasses.field(default_factory=list)


def check_table(ctx: TextContext, doc: Document) -> TableFit:
   """!Fits every text of a table (check_text()).
   @param ctx  the game's text settings
   @param doc  table Document
   @return TableFit
   """
   out = TableFit()
   for r in rows(doc):
      fit = check_text(ctx, doc, r.key, r)
      if fit.lines:
         out.checked += 1
      out.over += len(fit.over)
      out.with_placeholders += sum(1 for line in fit.lines if line.unmeasured)
      if fit.error is not None or fit.over:
         out.problems.append(fit)
   return out


# -- control codes ---------------------------------------------------------------------------------------------------

@dataclass
class ControlInfo:
   """!A control code the markup can write."""

   ## Its markup name.
   name: str
   ## Its byte after FC (or its own code for prompt / page).
   code: int
   ## The byte width of each argument.
   widths: tuple[int, ...]
   ## What it does (the engine header's comment).
   description: str

   def markup(self, args: Iterable[int] = ()) -> str:
      """!The control written in markup.
      @param args  its arguments (as many as widths; missing ones are 0)
      @return text, e.g. "{pause:15}"
      """
      values = list(args)[:len(self.widths)]
      values += [0] * (len(self.widths) - len(values))
      if not values:
         return "{" + self.name + "}"
      return "{" + self.name + ":" + encoder().ARG_SEPARATOR.join(str(v) for v in values) + "}"


def control_descriptions() -> dict[int, str]:
   """!What each control does, from the comments of capsule::text::Control in the engine's encode.h.
   @return control byte -> description ({} when the header cannot be read)
   """
   try:
      text = (engine.root() / "include" / ENCODE_HEADER).read_text(encoding="utf-8")
   except (OSError, engine.EngineNotFound):
      return {}
   start = text.find("enum class Control")
   out = {}
   for line in text[start:].splitlines()[1:]:
      if line.strip().startswith("};"):
         break
      m = CONTROL_LINE.match(line)
      if m:
         out[int(m.group("code"), HEX_BASE)] = m.group("doc").rstrip(".")
   return out


def controls() -> list[ControlInfo]:
   """!The control codes of the markup: the markup controls (prompt, page), then the generic ones in byte order.
   @return ControlInfo list
   """
   te = encoder()
   docs = control_descriptions()
   out = [ControlInfo(name, code, (), MARKUP_CONTROLS.get(name, "")) for name, code in te.CONTROLS.items()]
   for name, (code, widths) in sorted(te.CONTROL_CODES.items(), key=lambda kv: kv[1][0]):
      out.append(ControlInfo(name, code, tuple(widths), docs.get(code, "")))
   return out


def markup_names(ctx: TextContext) -> list[str]:
   """!Everything a text's braces may name: controls, the field placeholders, the terms (`@concept`) and the code
   page's named glyphs (`#name`).
   @param ctx  the game's text settings
   @return names inside braces
   """
   te = encoder()
   out = [c.name for c in controls()]
   if ctx.field is not None:
      out += list(ctx.field.codes)
      out += ["@" + t for t in (ctx.field.terms or {})]
   out += [te.GLYPH_PREFIX + n for n in getattr(ctx.page, "names", {})]
   return out
