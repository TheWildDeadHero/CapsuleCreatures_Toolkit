"""!Text box styles: asset kind "text_box" (engine C10, asset::TextBox) for the text box style editor [S2, S4].

A style is an asset of the manifest: {"key": "text_box:NAME", "kind": "text_box", "font": "font:NAME", "fonts":
{"n": "font:OTHER"}, "window": {...}, "frame": {...}}. "window" holds text::window::Config's settings (the layer,
char block, rectangle in map cells, text margins, lines, palette entries, typing, its speed and speed-up, the arrow,
the first RAM tile, the palette bank), "frame" text::window::Frame's (the nine frame tiles' first tile, their
palette bank, inside padding per side), "font" the window's font and "fonts" the fonts its Font control n selects.
The engine's asset compiler (compile_text_box(), text_box_lines()) is the authority: the settings and their ranges
are its TEXT_BOX_WINDOW / TEXT_BOX_FRAME, typing and speedup its words (TEXT_BOX_TYPING, TEXT_BOX_SPEEDUP);
config_fields() joins them with window.h's member order, defaults and comments. A setting left out takes the
struct's default; char_block left out is the layer's own block and arrow left out is no arrow (optional fields).
Preview data (colours of the bank, the generated frame art's entries or a 24x24 frame picture) is the asset's
editor data ("editor": {"preview": ...}: the compiler drops every "editor" key).

S2 kept styles as manifest editor data ("editor": {"text_boxes": [...]}) with a C++ header export: legacy_styles()
lists them and migrate() turns them into text_box assets (the header is gone: the engine builds asset::text_box()).

check() reports what the engine refuses (its compiler's message, a font that is no font asset of the manifest) or
draws wrongly; frame_cells() places the frame's parts as window.cpp draw_frame() does; typing() types a text with
core.text_window (window.cpp's typing and speed-up, frame by frame) and preview() draws the box on a 240x160 screen
at a frame of it. fit_box() is the box a text table fits its authored texts in.

S5 (engine N3): a style's art is engine data too: "palette" (the window bank's colours, entries 1-15), the window's
"arrow_image" ({image: an 8-pixel-wide palette PNG, height, steps, delay}: Config arrow_kind kArrowImage, the
prompt arrow stepping through the image's rows at the pen), the frame's "image" (a 24x24 palette PNG of the nine
parts) and "palette" (the frame bank's colours). They win over the editor's preview data (colors, frame_image),
which stays for styles without them. A style's "menu" (ui::MenuStyle) is core.menu_styles'. kMaxTiles (256 since N3)
is read from window.h like every other limit.

Qt-free; the text box panel (ui/editors/text_boxes.py) and `capsule-studio text-box ...` use it.
"""
from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import engine, text_render, text_window
from .document import Document, DocumentError

## A parsed JSON object (a style).
JsonDict = dict[str, Any]
## The asset kind of a style.
KIND = "text_box"
## The key prefix of a style.
KEY_PREFIX = "text_box:"
## S2's key of the styles in the asset manifest's "editor" object (legacy_styles(), migrate()).
STYLES_KEY = "text_boxes"
## The editor data key of a style's preview settings.
PREVIEW_KEY = "preview"
## The engine header of text windows.
WINDOW_HEADER = "capsule/text/window.h"
## The engine header of the video layer (types, screen, layers, map cells).
VIDEO_HEADER = "capsule/hal/video.h"
## The engine header of the text codes (the Code type, kCodeEnd).
ENCODE_HEADER = "capsule/text/encode.h"
## The headers whose integer type aliases and constants the fields' types and defaults use.
HEADERS = (WINDOW_HEADER, VIDEO_HEADER, ENCODE_HEADER)
## A member of a struct in a header: its type, name and default, then its doc comment.
MEMBER = re.compile(r"^\s*(?P<type>[\w:]+\*?)\s+(?P<name>\w+)\s*=\s*(?P<default>[\w:]+)\s*;\s*///<\s*(?P<doc>.*)$")
## An integer alias: `using Name = uint16_t;`.
ALIAS = re.compile(r"\busing\s+(?P<name>\w+)\s*=\s*(?P<type>u?int\d+_t)\s*;")
## An integer constant: `inline constexpr TYPE name = value;` (decimal or hex).
CONSTANT = re.compile(r"\bconstexpr\s+[\w:]+\s+(?P<name>\w+)\s*=\s*(?P<value>0[xX][0-9A-Fa-f]+|\d+)\b")
## A constant naming another: `inline constexpr Code kNoArrow = kCodeEnd;`.
CONSTANT_ALIAS = re.compile(r"\bconstexpr\s+[\w:]+\s+(?P<name>\w+)\s*=\s*(?P<other>k\w+)\s*;")
## A fixed-width integer type's name: (u)int<bits>_t.
INT_TYPE = re.compile(r"(?P<unsigned>u?)int(?P<bits>\d+)_t")
## The structs a style holds: (header struct, style key).
STRUCTS = (("Config", "window"), ("Frame", "frame"))
## Window settings a style may leave out to mean something of their own: char_block (the layer's block), arrow (no
## arrow).
OPTIONAL = ("char_block", "arrow")
## Frame tiles per row and parts (window.h kFrameColumns, kFrameParts) when the header cannot be read.
DEFAULT_FRAME_COLUMNS, DEFAULT_FRAME_PARTS = 3, 9
## The settings of a new style besides the defaults: a two-line box over the screen's bottom rows.
NEW_WINDOW = {"x": 2, "y": 15, "width": 26, "height": 4, "top": 1, "lines": 2, "background": 1, "ink": 2,
              "shadow": 3}
## The frame of a new style: one cell of padding at the left (the frame's inside before the text).
NEW_FRAME = {"pad_left": 1}
## Preview data of a new style: the generated frame art's outer and inner entries (the colours are added).
NEW_PREVIEW = {"frame_entries": [4, 5]}
## Pixels of the generated frame art's line (an outer and an inner pixel).
FRAME_LINE_PIXELS = 2
## Bits of a byte (map cells' sizes are counted from their type's bits).
BYTE_BITS = 8
## A legacy style's members the engine's text_box has no setting for (they came with window.h's Config).
LEGACY_DROPPED = ("font_count",)
## S5 (N3): a style's window bank colours (asset::TextBox::palette).
PALETTE_KEY = "palette"
## S5 (N3): the window's arrow image object (asset_compiler TEXT_BOX_ARROW_KEYS).
ARROW_IMAGE_KEY = "arrow_image"
## S5 (N3): the frame's art: its 24x24 image and its bank's colours (asset_compiler TEXT_BOX_FRAME_ART).
FRAME_IMAGE_KEY, FRAME_PALETTE_KEY = "image", "palette"
## S5 (N3): the arrow image's settings and what a new one starts with (one step showing the image's top rows).
NEW_ARROW = {"steps": [0], "delay": 0}


@dataclass
class Field:
   """!One setting of a style: a member of window::Config or window::Frame the engine's text_box takes."""

   ## Its struct key in the style ("window" or "frame").
   group: str
   ## The member's name.
   name: str
   ## Its C++ type as written.
   ctype: str
   ## Its default value (a word for a word setting, None for an optional one).
   default: Any
   ## Lowest value (0 for a word setting).
   low: int
   ## Highest value (the last word's index for a word setting).
   high: int
   ## The header's comment.
   doc: str
   ## The words it is written as (typing, speedup), or ().
   words: tuple[str, ...] = ()
   ## Whether leaving it out means something of its own (OPTIONAL).
   optional: bool = False


def _header(name: str) -> str:
   """!An engine header's text.
   @param name  path below include/
   @return text ("" when it cannot be read)
   """
   try:
      return (engine.root() / "include" / name).read_text(encoding="utf-8")
   except (OSError, engine.EngineNotFound):
      return ""


def constants() -> dict[str, int]:
   """!The integer constants of the headers a style uses (window.h, hal/video.h, encode.h).
   @return name -> value
   """
   out = {}
   texts = [_header(h) for h in HEADERS]
   for text in texts:
      for m in CONSTANT.finditer(text):
         out[m.group("name")] = int(m.group("value"), 0)
   for text in texts:
      for m in CONSTANT_ALIAS.finditer(text):
         if m.group("other") in out:
            out.setdefault(m.group("name"), out[m.group("other")])
   return out


def _aliases() -> dict[str, str]:
   """!The integer type aliases of the headers (BgIndex, TileIndex, Code, MapCell, ...).
   @return alias -> its fixed-width type
   """
   out = {}
   for h in HEADERS:
      for m in ALIAS.finditer(_header(h)):
         out[m.group("name")] = m.group("type")
   return out


def _range(ctype: str, aliases: dict[str, str]) -> tuple[int, int] | None:
   """!The values a member's type holds.
   @param ctype    its type as written (namespaces allowed)
   @param aliases  the headers' aliases
   @return (low, high), or None for a type that is no integer
   """
   base = ctype.split("::")[-1]
   m = INT_TYPE.fullmatch(aliases.get(base, base))
   if m is None:
      return None
   bits = int(m.group("bits"))
   if m.group("unsigned"):
      return 0, (1 << bits) - 1
   return -(1 << (bits - 1)), (1 << (bits - 1)) - 1


def _header_members() -> list[tuple[str, str, str, int, str]]:
   """!The integer members of window.h's Config and Frame: (group, name, type, default, comment) in header order.
   @return members
   """
   text = _header(WINDOW_HEADER)
   aliases = _aliases()
   consts = constants()
   out = []
   for struct, group in STRUCTS:
      start = text.find(f"struct {struct}\n")
      if start < 0:
         continue
      end = text.find("};", start)
      for line in text[start:end].splitlines():
         m = MEMBER.match(line)
         if m is None or _range(m.group("type"), aliases) is None:
            continue
         raw = m.group("default")
         default = consts.get(raw.split("::")[-1]) if not raw.isdigit() else int(raw)
         out.append((group, m.group("name"), m.group("type"), default or 0, m.group("doc").strip()))
   return out


def config_fields() -> list[Field]:
   """!The settings of a style: the engine compiler's text_box settings (TEXT_BOX_WINDOW, TEXT_BOX_FRAME, the word
   settings) in window.h's member order, with the header's defaults and comments (worked out once per engine and
   window.h version).
   @return fields (window, then frame); [] without the engine's text_box (an engine before C10)
   """
   try:
      header = engine.root() / "include" / WINDOW_HEADER
      stamp = (str(header), header.stat().st_mtime_ns)
   except (OSError, engine.EngineNotFound):
      stamp = ("", 0)
   if stamp not in _FIELDS_CACHE:
      _FIELDS_CACHE.clear()
      _FIELDS_CACHE[stamp] = _config_fields()
   return list(_FIELDS_CACHE[stamp])


## config_fields() by (window.h path, its time).
_FIELDS_CACHE: dict[tuple[str, int], list[Field]] = {}


def _config_fields() -> list[Field]:
   """!config_fields() worked out (no cache).
   @return fields
   """
   ac = engine.asset_compiler()
   ranges = {"window": dict(getattr(ac, "TEXT_BOX_WINDOW", {})), "frame": dict(getattr(ac, "TEXT_BOX_FRAME", {}))}
   words = {"typing": tuple(getattr(ac, "TEXT_BOX_TYPING", ())), "speedup": tuple(getattr(ac, "TEXT_BOX_SPEEDUP", ()))}
   defaults = dict(getattr(ac, "TEXT_BOX_DEFAULTS", {}))
   if not ranges["window"]:
      return []
   members = {(g, n): (t, d, doc) for g, n, t, d, doc in _header_members()}
   order = [(g, n) for g, n, *_rest in _header_members()]
   for group in ("window", "frame"):
      for name in list(ranges[group]) + ([w for w in words if words[w]] if group == "window" else []):
         if (group, name) not in order:
            order.append((group, name))   # a setting window.h does not spell as a member (kept, compiler last)
   out = []
   for group, name in sorted(order, key=lambda gn: (gn[0] != "window", order.index(gn))):
      ctype, default, doc = members.get((group, name), ("uint8_t", defaults.get(name, 0), ""))
      if name in words and group == "window" and words[name]:
         w = words[name]
         index = default if isinstance(default, int) and 0 <= default < len(w) else 0
         out.append(Field(group, name, ctype, w[index], 0, len(w) - 1, doc, w))
      elif name in ranges[group]:
         lo, hi = ranges[group][name]
         optional = group == "window" and name in OPTIONAL
         out.append(Field(group, name, ctype, None if optional else defaults.get(name, default), lo, hi, doc,
                          optional=optional))
   return out


def field_of(group: str, name: str) -> Field | None:
   """!One setting's Field.
   @param group  "window" or "frame"
   @param name   the member
   @return Field, or None when the engine has no such setting
   """
   return next((f for f in config_fields() if f.group == group and f.name == name), None)


@dataclass
class Limits:
   """!The engine's limits a style must keep."""

   ## Most cells one window covers (window::kMaxTiles).
   max_tiles: int
   ## Background layers (hal::video::kNumBgs).
   layers: int
   ## Pixels per tile side (hal::video::kTileSize).
   tile: int
   ## Screen size in cells (kScreenWidth / kScreenHeight over kTileSize).
   screen: tuple[int, int]
   ## Map cells per side of a layer's map (kScreenBlockTiles).
   map_cells: int
   ## Palette banks a map cell names (its bits above kMapPaletteShift).
   banks: int
   ## Highest tile a map cell names (kMapTileMask).
   max_tile: int
   ## The frame's parts per row and in all (window::kFrameColumns, kFrameParts).
   frame: tuple[int, int]


def limits() -> Limits:
   """!The engine's limits, from its headers.
   @return Limits
   @throws DocumentError when the headers lack them (an engine before I4)
   """
   c = constants()
   need = ("kMaxTiles", "kNumBgs", "kTileSize", "kScreenWidth", "kScreenHeight", "kScreenBlockTiles",
           "kMapPaletteShift", "kMapTileMask")
   missing = [n for n in need if n not in c]
   if missing:
      raise DocumentError(f"the engine's headers lack {', '.join(missing)} (text windows came with engine I4)")
   cell_range = _range("MapCell", _aliases())
   cell_bits = (cell_range[1] + 1).bit_length() - 1 if cell_range else BYTE_BITS + BYTE_BITS
   tile = c["kTileSize"]
   return Limits(c["kMaxTiles"], c["kNumBgs"], tile, (c["kScreenWidth"] // tile, c["kScreenHeight"] // tile),
                 c["kScreenBlockTiles"], 1 << (cell_bits - c["kMapPaletteShift"]), c["kMapTileMask"],
                 (c.get("kFrameColumns", DEFAULT_FRAME_COLUMNS), c.get("kFrameParts", DEFAULT_FRAME_PARTS)))


# -- styles in a manifest -------------------------------------------------------------------------------------------

def styles(doc: Document) -> list[JsonDict]:
   """!The manifest's text box styles (its text_box assets, in manifest order).
   @param doc  asset manifest Document
   @return the assets (live; change them only inside Document.edit())
   """
   return doc.assets(KIND)


def keys(doc: Document) -> list[str]:
   """!The styles' keys.
   @param doc  asset manifest Document
   @return keys in manifest order
   """
   return [str(s.get("key")) for s in styles(doc)]


def find(doc: Document, key: str) -> JsonDict:
   """!A style by key.
   @param doc  asset manifest Document
   @param key  its key ("text_box:NAME")
   @return the asset (live)
   @throws DocumentError when there is none
   """
   for s in styles(doc):
      if s.get("key") == key:
         return s
   raise DocumentError(f"no text box style {key!r}")


def new_style(key: str, font: str | None = None) -> JsonDict:
   """!A style with NEW_WINDOW / NEW_FRAME and the neutral preview colours (the rest left at their defaults).
   @param key   its key
   @param font  its font's asset key, or None
   @return the asset
   """
   preview = copy.deepcopy(NEW_PREVIEW)
   preview["colors"] = [text_render.color_text(c) for c in text_render.default_colors()]
   out: JsonDict = {"key": key, "kind": KIND}
   if font:
      out["font"] = font
   out["window"] = dict(NEW_WINDOW)
   out["frame"] = dict(NEW_FRAME)
   out["editor"] = {PREVIEW_KEY: preview}
   return out


def add_style(doc: Document, key: str, font: str | None = None, like: str | None = None) -> JsonDict:
   """!Adds a style (call inside Document.edit()).
   @param doc   asset manifest Document
   @param key   a new key ("text_box:NAME"; a bare NAME gets the prefix)
   @param font  its font's asset key, or None
   @param like  a style to copy, or None for a new one
   @return the asset
   """
   key = full_key(key)
   doc.check_new_key(key)
   style = copy.deepcopy(find(doc, like)) if like is not None else new_style(key, font)
   style["key"] = key
   if font is not None:
      style["font"] = font
   doc.data.setdefault("assets", []).append(style)
   return style


def full_key(key: str) -> str:
   """!A style's key with its prefix.
   @param key  "text_box:NAME" or NAME
   @return "text_box:NAME"
   """
   key = str(key).strip()
   if not key:
      raise DocumentError("a style has a key (text_box:NAME)")
   return key if key.startswith(KEY_PREFIX) else KEY_PREFIX + key


def remove_style(doc: Document, key: str) -> None:
   """!Removes a style (call inside Document.edit()).
   @param doc  asset manifest Document
   @param key  its key
   @return None
   """
   style = find(doc, key)
   doc.data["assets"].remove(style)


def set_value(doc: Document, key: str, group: str, name: str, value: Any) -> None:
   """!Changes one setting of a style (call inside Document.edit()): a window / frame setting (a number in the
   engine's range, a word, or None: left out), the font ("font"), the key ("key"), or a preview setting ("preview":
   colors, frame_entries, frame_image).
   @param doc    asset manifest Document
   @param key    the style
   @param group  "window", "frame", "preview" or "" (the style's own keys)
   @param name   the setting
   @param value  its value
   @return None
   @throws DocumentError for an unknown setting or a value the engine refuses
   """
   style = find(doc, key)
   if (group, name) in ((ART_GROUP_WINDOW, ARROW_IMAGE_KEY), ("frame", FRAME_IMAGE_KEY), ("frame", FRAME_PALETTE_KEY),
                        ("", PALETTE_KEY)):
      _set_art(style, group, name, value)
      return
   if group in ("window", "frame"):
      f = field_of(group, name)
      if f is None:
         raise DocumentError(f"the engine's text_box has no {group} setting {name!r}")
      part = style.setdefault(group, {})
      if value is None:
         part.pop(name, None)
      elif f.words:
         if value not in f.words:
            raise DocumentError(f"{name} is one of {', '.join(f.words)}")
         part[name] = value
      elif isinstance(value, bool) or not isinstance(value, int) or not f.low <= value <= f.high:
         raise DocumentError(f"{name} is {f.low}-{f.high}")
      else:
         part[name] = value
      if not part:
         style.pop(group, None)
      return
   if group == PREVIEW_KEY:
      _set_preview(style.setdefault("editor", {}).setdefault(PREVIEW_KEY, {}), name, value)
      return
   if name == "key":
      new = full_key(value)
      doc.check_new_key(new, ignore=style)
      style["key"] = new
   elif name == "font":
      if value:
         style["font"] = value
      else:
         style.pop("font", None)
   else:
      raise DocumentError(f"a style has no setting {name!r}")


## S5: the window's group key (the arrow image lives in it).
ART_GROUP_WINDOW = "window"


def _set_art(style: JsonDict, group: str, name: str, value: Any) -> None:
   """!S5 (N3): changes a piece of a style's art: its palette, the window's arrow image, the frame's image or palette
   (None: left out). Colours are hex colour texts; an image is a path relative to the manifest with '/' separators. The
   engine's compiler checks the rest (compile_style() with the manifest's folder: the images' sizes and indices).
   @param style  the style
   @param group  "" (palette), "window" (arrow_image) or "frame" (image, palette)
   @param name   the key
   @param value  its value, or None
   @return None
   @throws DocumentError for a value of the wrong shape
   """
   part = style if group == "" else style.setdefault(group, {})
   if value is None:
      part.pop(name, None)
   elif name == PALETTE_KEY:
      most = text_render.bank_colors() - 1   # entry 0 is transparent: the palette gives entries 1-15
      if not isinstance(value, list) or not 0 < len(value) <= most:
         raise DocumentError(f"a palette is 1-{most} colours (#rrggbb) for entries 1-{most}")
      try:
         part[name] = [text_render.color_text(text_render.parse_color(str(c))) for c in value]
      except ValueError as e:
         raise DocumentError(str(e)) from None
   elif name == FRAME_IMAGE_KEY:
      part[name] = _relative_path(value)
   else:
      if not isinstance(value, dict):
         raise DocumentError("an arrow image is {image, height, steps, delay}")
      keys = set(getattr(engine.asset_compiler(), "TEXT_BOX_ARROW_KEYS", ()))
      extra = sorted(set(value) - keys)
      if extra:
         raise DocumentError(f"an arrow image has no setting {', '.join(extra)} (it takes {', '.join(sorted(keys))})")
      arrow = dict(value)
      arrow["image"] = _relative_path(arrow.get("image"))
      part[name] = arrow
   if group and not part:
      style.pop(group, None)


def _relative_path(value: Any) -> str:
   """!An image path as a manifest writes it.
   @param value  the path
   @return it with '/' separators
   @throws DocumentError for an empty or absolute path
   """
   text = str(value or "").strip().replace("\\", "/")
   if not text or Path(text).is_absolute():
      raise DocumentError("an image is a path relative to the manifest")
   return Path(text).as_posix()


def arrow_image(style: JsonDict) -> JsonDict | None:
   """!S5 (N3): a style's arrow image settings as written.
   @param style  the style
   @return {"image", "height", "steps", "delay"} (keys left out stay out), or None
   """
   window = style.get(ART_GROUP_WINDOW)
   found = window.get(ARROW_IMAGE_KEY) if isinstance(window, dict) else None
   return found if isinstance(found, dict) else None


def frame_image(style: JsonDict) -> str | None:
   """!S5 (N3): the frame's image path.
   @param style  the style
   @return the path, or None
   """
   frame = style.get("frame")
   found = frame.get(FRAME_IMAGE_KEY) if isinstance(frame, dict) else None
   return str(found) if found else None


def compiled_arrow(style: JsonDict, base: Path | None) -> JsonDict | None:
   """!S5 (N3): a style's arrow image compiled by the engine (asset_compiler.compile_arrow_image()).
   @param style  the style
   @param base   the manifest's folder (the image's path is relative to it), or None
   @return {"rows", "height", "steps", "delay"}, or None without an arrow image (or one the engine refuses: check())
   """
   arrow = arrow_image(style)
   ac = engine.asset_compiler()
   if arrow is None or base is None or not hasattr(ac, "compile_arrow_image"):
      return None
   try:
      return ac.compile_arrow_image(arrow, base, None, str(style.get("key")))
   except (ac.ManifestError, OSError, TypeError, ValueError):
      return None


def set_control_font(doc: Document, key: str, number: int, font: str | None) -> None:
   """!The font a style's Font control n selects (call inside Document.edit()).
   @param doc     asset manifest Document
   @param key     the style
   @param number  the control's number (0 to the compiler's MAX_TEXT_BOX_FONTS - 1)
   @param font    a font asset's key, or None to take it out
   @return None
   """
   most = int(getattr(engine.asset_compiler(), "MAX_TEXT_BOX_FONTS", 0))
   if isinstance(number, bool) or not isinstance(number, int) or not 0 <= number < most:
      raise DocumentError(f"a Font control's number is 0-{most - 1}")
   style = find(doc, key)
   table = style.setdefault("fonts", {})
   if font:
      table[str(number)] = font
   else:
      table.pop(str(number), None)
   if not table:
      style.pop("fonts", None)
   else:
      style["fonts"] = {str(n): table[str(n)] for n in sorted(int(k) for k in table)}


def control_fonts(style: JsonDict) -> dict[int, str]:
   """!A style's Font control fonts.
   @param style  the style
   @return number -> font key (numbers that are no numbers left out)
   """
   table = style.get("fonts")
   if not isinstance(table, dict):
      return {}
   return {int(n): str(v) for n, v in table.items() if str(n).isdigit()}


def _set_preview(preview: JsonDict, key: str, value: Any) -> None:
   """!Changes a preview setting.
   @param preview  the style's editor "preview" object
   @param key      colors (a list of hex colours rrggbb), frame_entries ([outer, inner]), frame_image (a path or None)
   @param value    its value
   @return None
   """
   if key == "colors":
      if not isinstance(value, list) or len(value) > text_render.bank_colors():
         raise DocumentError(f"colors are at most {text_render.bank_colors()} hex colours (#rrggbb)")
      try:
         preview["colors"] = [text_render.color_text(text_render.parse_color(str(c))) for c in value]
      except ValueError as e:
         raise DocumentError(str(e)) from None
   elif key == "frame_entries":
      if not (isinstance(value, list) and len(value) == FRAME_LINE_PIXELS and all(
            isinstance(v, int) and 0 <= v < text_render.bank_colors() for v in value)):
         raise DocumentError(f"frame_entries are {FRAME_LINE_PIXELS} palette entries (outer, inner)")
      preview["frame_entries"] = list(value)
   elif key == "frame_image":
      if value:
         preview["frame_image"] = Path(str(value)).as_posix()
      else:
         preview.pop("frame_image", None)
   else:
      raise DocumentError(f"a style's preview has no setting {key!r}")


def preview_data(style: JsonDict) -> JsonDict:
   """!A style's preview settings.
   @param style  the style
   @return its editor "preview" object ({} without one)
   """
   editor = style.get("editor")
   found = editor.get(PREVIEW_KEY) if isinstance(editor, dict) else None
   return found if isinstance(found, dict) else {}


def value(style: JsonDict, group: str, key: str) -> Any:
   """!A window / frame setting as written, else its default.
   @param style  the style
   @param group  "window" or "frame"
   @param key    the member
   @return a number, a word (typing, speedup), or None (an optional setting left out)
   """
   f = field_of(group, key)
   given = (style.get(group) or {}).get(key)
   if f is not None and f.words:
      return given if given in f.words else f.default
   if isinstance(given, int) and not isinstance(given, bool):
      return given
   return f.default if f is not None else 0


def number(style: JsonDict, group: str, key: str) -> int:
   """!A setting as the engine's struct holds it: a word's index, char_block left out the layer's
   (asset_compiler LAYER_CHAR_BLOCK), arrow left out kNoArrow.
   @param style  the style
   @param group  "window" or "frame"
   @param key    the member
   @return the number
   """
   v = value(style, group, key)
   f = field_of(group, key)
   if f is not None and f.words:
      return f.words.index(v)
   if v is None:
      if key == "arrow":
         return int(text_render.encoder().CODE_END)
      return int(getattr(engine.asset_compiler(), "LAYER_CHAR_BLOCK", 0))
   return int(v)


def settings(style: JsonDict, base: Path | None = None) -> dict[str, Any]:
   """!A style's window settings for core.text_window (arrow left out when the style has none; S5: the arrow image's
   when it has one the engine compiles).
   @param style  the style
   @param base   S5: the manifest's folder (the arrow image), or None
   @return Config member -> number (arrow_rows / arrow_offsets: lists)
   """
   out: dict[str, Any] = {f.name: number(style, "window", f.name) for f in config_fields() if f.group == "window"}
   if value(style, "window", "arrow") is None:
      out.pop("arrow", None)
   arrow = compiled_arrow(style, base)
   if arrow is not None:
      out.update({"arrow_kind": text_window.header_constants()["kArrowImage"], "arrow_rows": list(arrow["rows"]),
                  "arrow_height": arrow["height"], "arrow_offsets": list(arrow["steps"]),
                  "arrow_delay": arrow["delay"]})
   return out


# -- S2's editor-data styles ------------------------------------------------------------------------------------------

def legacy_styles(doc: Document) -> list[JsonDict]:
   """!S2's text box styles kept as the manifest's editor data ("editor": {"text_boxes": [...]}).
   @param doc  asset manifest Document
   @return the styles (live)
   """
   editor = doc.data.get("editor")
   found = editor.get(STYLES_KEY) if isinstance(editor, dict) else None
   return found if isinstance(found, list) else []


def legacy_key(name: str) -> str:
   """!The asset key a legacy style's name becomes: text_box: and the name in capitals, other characters '_'.
   @param name  the name
   @return the key
   """
   return KEY_PREFIX + (re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper() or "STYLE")


def migrate(doc: Document) -> list[tuple[str, str, list[str]]]:
   """!Turns S2's editor-data styles into text_box assets (call inside Document.edit()): each style's window and
   frame settings the engine takes (a value outside its range, the legacy-only members and an arrow of kNoArrow are
   left out), its font, its preview data; the editor list is removed.
   @param doc  asset manifest Document
   @return per style (its name, the new key, the settings left out)
   """
   out = []
   fields = {(f.group, f.name): f for f in config_fields()}
   no_arrow = int(text_render.encoder().CODE_END)
   for old in list(legacy_styles(doc)):
      name = str(old.get("name", "style"))
      key = legacy_key(name)
      n = 1
      while doc.find(key) is not None:
         n += 1
         key = f"{legacy_key(name)}_{n}"
      asset: JsonDict = {"key": key, "kind": KIND}
      if old.get("font"):
         asset["font"] = old["font"]
      dropped = []
      for group in ("window", "frame"):
         part = {}
         for k, v in (old.get(group) or {}).items():
            f = fields.get((group, k))
            ok = f is not None and not f.words and isinstance(v, int) and not isinstance(v, bool) and \
               f.low <= v <= f.high
            if k == "arrow" and v == no_arrow:
               continue   # kNoArrow: the asset leaves arrow out
            if ok:
               part[k] = v
            else:
               dropped.append(f"{group}.{k}")
         if part:
            asset[group] = part
      if isinstance(old.get(PREVIEW_KEY), dict):
         asset["editor"] = {PREVIEW_KEY: copy.deepcopy(old[PREVIEW_KEY])}
      doc.data.setdefault("assets", []).append(asset)
      out.append((name, key, dropped))
   editor = doc.data.get("editor")
   if isinstance(editor, dict):
      editor.pop(STYLES_KEY, None)
      if not editor:
         doc.data.pop("editor")
   return out


# -- what the engine draws -------------------------------------------------------------------------------------------

def frame_cells(style: JsonDict) -> dict[tuple[int, int], int]:
   """!The frame's cells and the part each shows, as window.cpp draw_frame() writes them: a ring one cell outside the
   window's rectangle grown by the padding, the padding's cells the inside part; the window's own cells and cells
   left of or above the map are left out.
   @param style  the style
   @return (x, y) -> part (row * frame columns + column)
   """
   lim = limits()
   columns = lim.frame[0]
   w = {k: number(style, "window", k) for k in ("x", "y", "width", "height")}
   f = {k: number(style, "frame", k) for k in ("pad_left", "pad_top", "pad_right", "pad_bottom")}
   x0, y0 = w["x"] - f["pad_left"] - 1, w["y"] - f["pad_top"] - 1
   x1, y1 = w["x"] + w["width"] + f["pad_right"], w["y"] + w["height"] + f["pad_bottom"]
   out = {}
   for y in range(y0, y1 + 1):
      for x in range(x0, x1 + 1):
         inside = w["x"] <= x < w["x"] + w["width"] and w["y"] <= y < w["y"] + w["height"]
         if inside or x < 0 or y < 0:
            continue
         out[(x, y)] = _part(y, y0, y1) * columns + _part(x, x0, x1)
   return out


def _part(v: int, lo: int, hi: int) -> int:
   """!A cell's part column or row along one axis (window.cpp part_of()).
   @param v   the cell
   @param lo  the near border cell
   @param hi  the far border cell
   @return 0 (near edge), 1 (inside) or the far edge
   """
   far = DEFAULT_FRAME_COLUMNS - 1
   return 0 if v == lo else (far if v == hi else 1)


def font_keys(doc: Document) -> list[str]:
   """!The font assets a style may name: the manifest's (and its includes') font assets.
   @param doc  asset manifest Document
   @return keys
   """
   from . import asset_tables
   found = [label for label, _p in asset_tables.fonts(doc) if label.startswith("font:")] if doc.base_dir else []
   own = [str(a.get("key")) for a in doc.assets("font")]
   return list(dict.fromkeys(own + found))


def compile_style(style: JsonDict, base: Path | None = None) -> JsonDict:
   """!A style compiled by the engine (asset_compiler.compile_text_box()).
   @param style  the style
   @param base   S5: the manifest's folder (N3: the arrow and frame images' paths are relative to it), or None: a
                 style with images is compiled without them (their settings only)
   @return its record
   @throws DocumentError with the compiler's message
   """
   ac = engine.asset_compiler()
   where = str(style.get("key"))
   try:
      bare = ac.strip(style)
      ac.check_keys(bare, ac.KIND_KEYS[KIND], where)
      if base is None and (arrow_image(bare) is not None or frame_image(bare) is not None):
         bare = copy.deepcopy(bare)   # no folder to read the images from: compile the rest
         bare.get(ART_GROUP_WINDOW, {}).pop(ARROW_IMAGE_KEY, None)
         bare.get("frame", {}).pop(FRAME_IMAGE_KEY, None)
      if base is None:
         return ac.compile_text_box(bare, where)
      return ac.compile_text_box(bare, where, base, None)
   except (ac.ManifestError, KeyError, TypeError, ValueError, OSError) as e:
      raise DocumentError(str(e)) from None


def check(style: JsonDict, font: JsonDict | None = None, fonts: list[str] | None = None,
          base: Path | None = None) -> list[str]:
   """!What the engine would refuse or draw wrongly with a style.
   @param style  the style
   @param font   its compiled font (compile_proportional()), or None (the line checks are skipped)
   @param fonts  the manifest's font asset keys (font_keys()), or None (not checked)
   @param base   S5: the manifest's folder (the art's images are checked), or None
   @return problems ("error: ..." refused or clipped, "warning: ..." drawn but off the screen / map)
   """
   out = []
   try:
      compile_style(style, base)
   except DocumentError as e:
      out.append(f"error: {e}")
   if fonts is not None:
      if not style.get("font"):
         out.append("error: the style names no font (\"font\": a font asset of the manifest)")
      elif style["font"] not in fonts:
         out.append(f"error: font {style['font']!r} is no font asset of this manifest")
      for n, key in sorted(control_fonts(style).items()):
         if key not in fonts:
            out.append(f"error: Font control {n}: {key!r} is no font asset of this manifest")
   lim = limits()
   w = {f.name: number(style, "window", f.name) for f in config_fields() if f.group == "window"}
   cells = w["width"] * w["height"]
   if cells > lim.max_tiles:
      out.append(f"error: the window covers {cells} cells; a window has {lim.max_tiles} tiles (window::kMaxTiles)")
   if w["width"] == 0 or w["height"] == 0:
      out.append("error: the window has no cells")
   if w["bg"] >= lim.layers:
      out.append(f"error: layer {w['bg']}: there are {lim.layers}")
   if w["palette_bank"] >= lim.banks:
      out.append(f"error: palette bank {w['palette_bank']}: a map cell names 0-{lim.banks - 1}")
   if number(style, "frame", "palette_bank") >= lim.banks:
      out.append(f"error: frame palette bank {number(style, 'frame', 'palette_bank')}: 0-{lim.banks - 1}")
   last_tile = w["first_tile"] + max(cells, 1) - 1
   if last_tile > lim.max_tile:
      out.append(f"error: the window's tiles end at {last_tile}; a map cell names tiles 0-{lim.max_tile}")
   if number(style, "frame", "first_tile") + lim.frame[1] - 1 > lim.max_tile:
      out.append(f"error: the frame's tiles end past {lim.max_tile}")
   if w["x"] + w["width"] > lim.map_cells or w["y"] + w["height"] > lim.map_cells:
      out.append(f"error: the window leaves the layer's {lim.map_cells}x{lim.map_cells} map")
   ring = frame_cells(style) if style.get("frame") is not None else {}
   right, bottom = lim.screen
   if any(x >= right or y >= bottom for x, y in ring) or w["x"] + w["width"] > right or w["y"] + w["height"] > bottom:
      out.append(f"warning: the box reaches past the {right}x{bottom}-cell screen")
   if ring and any(x >= lim.map_cells or y >= lim.map_cells for x, y in ring):
      out.append("error: the frame leaves the layer's map")
   if font is not None:
      height_px = w["height"] * lim.tile
      # the last line's lowest pixel row any glyph draws (a font's empty bottom rows are cut without loss)
      need = w["top"] + max(w["lines"] - 1, 0) * font["line_height"] + _inked_rows(font)
      if need > height_px:
         out.append(f"warning: {w['lines']} lines of {font['line_height']} pixels from {w['top']} reach pixel row "
                    f"{need}; the window is {height_px} high (the last line is cut)")
      if w["left"] >= w["width"] * lim.tile:
         out.append("error: the text starts past the window's right edge")
      arrow = compiled_arrow(style, base)
      if arrow is not None and w["top"] + max(w["lines"] - 1, 0) * font["line_height"] + arrow["height"] > height_px:
         out.append(f"warning: the arrow image ({arrow['height']} rows) at the last line reaches past the window's "
                    f"{height_px} pixel rows (cut)")
   from . import menu_styles   # local: core.menu_styles imports this module
   return out + menu_styles.check_menu(style, font)


def _inked_rows(font: JsonDict) -> int:
   """!How many rows from a glyph's top the font's glyphs draw (the lowest non-transparent row, plus one; S6b, C13a:
   at most the font's glyph_height rows, text_render.glyph_rows(), the rows a window draws).
   @param font  compiled font
   @return rows (0 for a font without pixels)
   """
   _cw, ch = font["cell"]
   row_bytes = len(font["glyphs"][0]) // ch if font["glyphs"] and ch else 0
   lowest = 0
   for packed in font["glyphs"]:
      for r in range(ch - 1, lowest - 1, -1):
         if any(packed[r * row_bytes:(r + 1) * row_bytes]):
            lowest = r + 1
            break
   return min(lowest, text_render.glyph_rows(font))


def storage(style: JsonDict) -> text_window.Storage:
   """!S6b (engine C13c): the tile storage a window of this style needs from the game (window::attach(): its
   width x height cells, kWordsPerTile words each), e.g. a static TileBuffer<W, H> or a screen arena block.
   @param style  the style
   @return text_window.Storage
   """
   return text_window.storage(number(style, "window", "width"), number(style, "window", "height"))


def fit_box(style: JsonDict, font_name: str | None) -> JsonDict:
   """!The box a text table fits its authored texts in for this style ("box" of capsule.texts/1): the window's width
   less its left margin, its lines.
   @param style      the style
   @param font_name  the table's name of the style's font, or None
   @return {"font", "width", "lines"} ("font" left out for None)
   """
   lim = limits()
   width = number(style, "window", "width") * lim.tile - number(style, "window", "left")
   out: JsonDict = {"width": max(width, 0), "lines": number(style, "window", "lines")}
   if font_name is not None:
      out = {"font": font_name, **out}
   return out


# -- preview ---------------------------------------------------------------------------------------------------------

def _colors(style: JsonDict, stored: Any) -> list[tuple[int, int, int]]:
   """!A bank's 16 colours: the preview's (else the neutral defaults), entries 1-15 from a stored palette.
   @param style   the style
   @param stored  a palette of the style's data (entries 1-15), or None
   @return colours by entry
   """
   colors = text_render.default_colors()
   given = list(preview_data(style).get("colors", []))
   if isinstance(stored, list):
      # entry 0 (the backdrop: transparent in the bank) stays the preview's; the palette gives entries 1-15
      given = (given[:1] or [text_render.color_text(colors[0])]) + [str(c) for c in stored]
   for i, c in enumerate(given[:len(colors)]):
      try:
         colors[i] = text_render.parse_color(str(c))
      except ValueError:
         continue
   return colors


def stored_palette(style: JsonDict) -> list[str] | None:
   """!S5 (N3): the window bank's colours the style stores ("palette").
   @param style  the style
   @return entries 1-15 as written, or None
   """
   found = style.get(PALETTE_KEY)
   return [str(c) for c in found] if isinstance(found, list) else None


def frame_palette(style: JsonDict) -> list[str] | None:
   """!S5 (N3): the frame bank's colours the style stores (frame "palette").
   @param style  the style
   @return entries 1-15 as written, or None
   """
   frame = style.get("frame")
   found = frame.get(FRAME_PALETTE_KEY) if isinstance(frame, dict) else None
   return [str(c) for c in found] if isinstance(found, list) else None


def pens(style: JsonDict) -> text_render.Pens:
   """!The entries and colours a style's text draws in (S5: its stored palette's colours win over the preview's).
   @param style  the style
   @return Pens
   """
   return text_render.Pens(number(style, "window", "ink"), number(style, "window", "shadow"),
                           number(style, "window", "background"), _colors(style, stored_palette(style)))


def frame_pens(style: JsonDict) -> text_render.Pens:
   """!S5 (N3): the colours the frame draws in: its own bank's (frame "palette"), else the window's.
   @param style  the style
   @return Pens
   """
   own = frame_palette(style)
   return pens(style) if own is None else text_render.Pens(
      number(style, "window", "ink"), number(style, "window", "shadow"), number(style, "window", "background"),
      _colors(style, own))


def frame_art(style: JsonDict, base: Path | None = None) -> list[list[list[int]]]:
   """!The nine frame parts as palette entries (8x8 each): the style's frame picture (a 24x24 palette PNG of the
   parts in reading order, its indices kept), else generated: an outer and an inner line of the style's two
   frame entries around the window's background (as a game's port may build them).
   @param style  the style
   @param base   the manifest's folder (the picture's path is relative to it), or None
   @return parts, each tile rows of entries
   """
   lim = limits()
   tile, columns, parts = lim.tile, lim.frame[0], lim.frame[1]
   preview = preview_data(style)
   rel = frame_image(style) or preview.get("frame_image")   # S5: the frame's own image (engine N3 data) first
   if rel and base is not None:
      bm = engine.bitmap()
      try:
         w, h, px = bm.read_png_indices(base / rel)
      except (bm.BitmapError, OSError):
         w = h = 0
      if w == tile * columns and h == tile * (parts // columns):
         return [[[px[(p // columns * tile + y) * w + p % columns * tile + x] for x in range(tile)]
                  for y in range(tile)] for p in range(parts)]
   outer, inner = (preview.get("frame_entries") or NEW_PREVIEW["frame_entries"])[:FRAME_LINE_PIXELS]
   fill = number(style, "window", "background")
   out = []
   far = columns - 1
   for p in range(parts):
      col, row = p % columns, p // columns
      rows = []
      for y in range(tile):
         line = []
         for x in range(tile):
            # distance to the frame's outside along each axis this part touches
            d = tile
            if col == 0:
               d = x
            elif col == far:
               d = tile - 1 - x
            if row == 0:
               d = min(d, y)
            elif row == far:
               d = min(d, tile - 1 - y)
            line.append(outer if d == 0 else (inner if d < FRAME_LINE_PIXELS else fill))
         rows.append(line)
      out.append(rows)
   return out


def typing(style: JsonDict, font: JsonDict, codes: list[int], keys: str = "advance",
           fonts: Mapping[int, JsonDict] | None = None,
           placeholders: Mapping[int, list[int]] | None = None, base: Path | None = None) -> text_window.Run:
   """!Types a text in a style's window, frame by frame (core.text_window: window.cpp's typing and speed-up).
   @param style         the style
   @param font          its compiled font
   @param codes         the text's codes
   @param keys          text_window.KEY_POLICIES: none, advance (a press at each wait), hold (Accept held)
   @param fonts         the Font control's compiled fonts by number, or None
   @param placeholders  what field placeholders show, or None
   @param base          S5: the manifest's folder (the arrow image), or None
   @return text_window.Run
   """
   return text_window.run(settings(style, base), font, codes, keys, fonts, placeholders)


def wait_frames(run: text_window.Run) -> list[int]:
   """!The frames the preview's Wait steps show: each wait's first frame, then the frame the text is done.
   @param run  a typing() result
   @return frames
   """
   last = run.done if run.done is not None else len(run.frames) - 1
   return list(run.waits) + ([last] if not run.waits or run.waits[-1] != last else [])


def preview(style: JsonDict, font: JsonDict | None, codes: list[int] | None = None, screen: int = 0,
            base: Path | None = None, placeholders: dict[int, list[int]] | None = None,
            frame: int | None = None, run: text_window.Run | None = None, keys: str = "advance",
            fonts: Mapping[int, JsonDict] | None = None) -> text_render.Canvas:
   """!The box on a screen: the backdrop (entry 0), the frame's cells and the window as it shows a text at a frame
   of its typing (frame None: the screen-th of wait_frames(), the frames a press is awaited at, then the end).
   @param style         the style
   @param font          its compiled font, or None (no text)
   @param codes         the text's codes, or None
   @param screen        which wait of the text (frame None)
   @param base          the manifest's folder (the frame picture), or None
   @param placeholders  what placeholders show, or None
   @param frame         a frame of the typing, or None
   @param run           the text's typing() result (a caller's cache), or None to type it here
   @param keys          the keys typing() presses (run None)
   @param fonts         the Font control's compiled fonts (run None)
   @return a Canvas of the screen
   """
   lim = limits()
   tile = lim.tile
   p = pens(style)
   canvas = text_render.Canvas(lim.screen[0] * tile, lim.screen[1] * tile, p.color(0))
   draw_frame(canvas, style, base)
   wx, wy = number(style, "window", "x") * tile, number(style, "window", "y") * tile
   ww, wh = number(style, "window", "width") * tile, number(style, "window", "height") * tile
   canvas.fill(wx, wy, ww, wh, p.color(p.background))
   if run is None and font is not None and codes:
      run = typing(style, font, codes, keys, fonts, placeholders, base)
   if run is not None:
      at = frame if frame is not None else wait_frames(run)[min(max(screen, 0), len(wait_frames(run)) - 1)]
      pixels = run.frame_at(at)
      rw, rh = run.size
      for y in range(min(rh, wh)):
         row = pixels[y * rw:(y + 1) * rw]
         for x in range(min(rw, ww)):
            canvas.put(wx + x, wy + y, p.color(row[x]))
   return canvas


def draw_frame(canvas: text_render.Canvas, style: JsonDict, base: Path | None) -> None:
   """!Draws a style's frame on a screen canvas (its cells as draw_frame() writes them, its art in its bank's colours).
   @param canvas  the screen
   @param style   the style
   @param base    the manifest's folder (the frame image), or None
   @return None
   """
   if style.get("frame") is None:
      return
   tile = limits().tile
   fp = frame_pens(style)
   art = frame_art(style, base)
   for (x, y), part in frame_cells(style).items():
      for r, row in enumerate(art[part]):
         for c, entry in enumerate(row):
            if entry:   # entry 0 is transparent in a 4bpp tile
               canvas.put(x * tile + c, y * tile + r, fp.color(entry))


## S5: pixels between two steps in arrow_strip().
STRIP_GAP = 2


def arrow_strip(style: JsonDict, base: Path | None) -> text_render.Canvas | None:
   """!S5 (N3): the arrow image's steps side by side (each the rows a wait shows at that step, over the window's
   background, in the window's colours), as window.cpp step_image_arrow() draws them.
   @param style  the style
   @param base   the manifest's folder, or None
   @return a Canvas, or None without an arrow image the engine compiles
   """
   arrow = compiled_arrow(style, base)
   if arrow is None:
      return None
   c = text_window.source_constants()
   width = text_window.header_constants()["kArrowImageWidth"]
   p = pens(style)
   steps, height, rows = arrow["steps"], arrow["height"], arrow["rows"]
   canvas = text_render.Canvas(len(steps) * (width + STRIP_GAP) - STRIP_GAP, height, p.color(0))
   for i, first in enumerate(steps):
      left = i * (width + STRIP_GAP)
      canvas.fill(left, 0, width, height, p.color(p.background))
      for r in range(height):
         if first + r >= len(rows):
            break
         for x in range(width):
            v = (rows[first + r] >> (x * c["kNibbleBits"])) & c["kNibbleMask"]
            if v:
               canvas.put(left + x, r, p.color(v))
   return canvas


def screen_count(style: JsonDict, codes: list[int], font: JsonDict | None = None, keys: str = "advance") -> int:
   """!How many waits (and the end) a text shows in a style's window.
   @param style  the style
   @param codes  the text's codes
   @param font   its compiled font, or None (counted from the codes without typing: text_render.screens())
   @param keys   the keys typing() presses
   @return screens
   """
   if font is None:
      return len(text_render.screens(codes, number(style, "window", "lines")))
   return len(wait_frames(typing(style, font, codes, keys)))


def describe_run(run: text_window.Run) -> str:
   """!One line about a typing: how long it took, its waits and presses.
   @param run  a typing() result
   @return text
   """
   done = f"done at frame {run.done}" if run.done is not None else f"not done after {len(run.frames) - 1} frames"
   waits = ", ".join(str(f) for f in run.waits) or "none"
   return f"{done}; waits begin at {waits}; {run.typed} frames drew"
