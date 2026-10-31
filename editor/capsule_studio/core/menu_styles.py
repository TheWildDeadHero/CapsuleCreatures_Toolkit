"""!Menu styles: a text box style's "menu" (engine N3, ui::MenuStyle in capsule/ui/menu.h) and a menu run frame by
frame as the engine's ui module runs it [S5].

A style's "menu" object holds how a menu drawn in its window looks and behaves: the option and cursor columns, the
first row and the rows' height, the cursor glyph and the rectangle a move clears, the wrap rule (never, always, above
n options), the frames before input is read, which presses move (pressed, repeated), when the move sound plays
(when_moved, always), the order keys act in (one_action, every_key), the keys that cancel, the four sounds and a
list's scroll arrows (a sprite, its two animations, the bounce). The engine's asset compiler is the authority:
menu_fields() takes the settings, their ranges and words from its TEXT_BOX_MENU / TEXT_BOX_MENU_NAMES /
MENU_KEY_NAMES / MENU_ORDER and joins them with menu.h's defaults and comments.

What a menu shows is the caller's (ui::Options: the options' texts, a grid's columns and column width, a list's
shown rows, the first cursor, whether cancel answers); the preview keeps them as the style's editor data
("editor": {"menu_preview": {...}}: the compiler drops "editor"), with the kind of menu (column, grid, list,
yes_no), the window's size (the style's, or fitted to the options as a game sizes a menu box per menu) and the
pad's repeat timing (ui::Repeat: a game's data in C++, so the preview's own setting).

run() opens a menu in a core.text_window.Window and feeds it one frame of keys at a time: KeyState is a port of
src/ui/keys.cpp (one repeat counter for the whole pad), Menu of src/ui/menu.cpp (open(), update(): the input
delay, one action or every key, Accept / cancel, column / grid / list moves with the middle-row scroll rule,
drawing with print_at() / fill()), and the scroll arrows of src/ui/arrows.cpp (hidden on the first update, shown
while the list can scroll their way, bob(): amplitude x sine / 256 from capsule/core/trig.h's table). A key script
(parse_script(): `down`, `down*40` held 40 frames, `wait 10`, `a`) gives the frames' keys. preview() draws a
frame of a run on a 240x160 screen: the frame, the window and stand-in arrows (the arrow sprite itself is not
drawn).

Qt-free; the menu style panel (ui/editors/menu_styles.py) and `capsule-studio text-box menu ...` use it.
"""
from __future__ import annotations

import copy
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import engine, text_boxes, text_render, text_window
from .document import Document, DocumentError

## A parsed JSON object.
JsonDict = dict[str, Any]
## A style's menu key.
MENU_KEY = "menu"
## The editor data key of a style's menu preview settings.
PREVIEW_KEY = "menu_preview"
## The engine header of menus (MenuStyle, Options, the word constants).
MENU_HEADER = "capsule/ui/menu.h"
## The engine header of the integer sine (the arrows' bounce).
TRIG_HEADER = "capsule/core/trig.h"
## The kinds of menu the preview shows: a column, a grid, a scrolling list, a yes / no box.
KINDS = ("column", "grid", "list", "yes_no")
## The menu setting a list's arrows name a sprite with.
SPRITE_FIELD = "arrow_sprite"
## The menu setting listing the keys that cancel.
CANCEL_FIELD = "cancel_keys"
## A member of MenuStyle: its type, name and default (up to the `;`), then its doc comment.
MEMBER = re.compile(r"^\s*(?P<type>[\w:]+)\s+(?P<name>\w+)\s*(?:=\s*(?P<default>[^;]+?)|\{\})\s*;"
                    r"\s*///<\s*(?P<doc>.*)$")
## A key in a KeyBits default: `key_bit(hal::input::KEY_B)`.
KEY_DEFAULT = re.compile(r"KEY_(?P<key>\w+)")
## An integer constant of a header (decimal or hex).
CONSTANT = re.compile(r"\bconstexpr\s+[\w:]+\s+(?P<name>k\w+)\s*=\s*(?P<value>0[xX][0-9A-Fa-f]+|\d+)\s*;")
## The quarter-wave table of trig.h: `kQuarterSineQ14[65] = { ... };`.
SINE_TABLE = re.compile(r"kQuarterSineQ14\[\d+\]\s*=\s*\{(?P<values>[^}]*)\}")
## trig.h's angle layout when the header cannot be read: steps per quadrant, the quadrant shift, first negative one.
DEFAULT_TRIG = {"kQuarterSteps": 64, "kQuadrantShift": 6, "kQuarterStepMask": 63, "kNegativeQuadrant": 2,
                "kQ14One": 16384}
## The bounce's sine unit (arrows.cpp kSineUnit: 1.0 and the divisor of amplitude * sine).
SINE_UNIT = 256
## A list's middle row: half its shown rows (menu.cpp kHalf).
HALF = 2
## menu.h's answers: nothing chosen this frame, a cancel.
NOTHING, CANCEL = -1, -2
## The pad's repeat in the preview when a style's editor data sets none: frames before the first repeat and between
## repeats (the engine's sandbox_menu and a handheld game keep 40 / 5 as their ui::Repeat).
DEFAULT_REPEAT = (40, 5)
## Frames a script's key word is held, then let go (a press).
PRESS_FRAMES = 1
## Frames run() goes on after the menu answered (the last picture stays).
AFTER_ANSWER = 1
## Most frames a run takes (a minute at 60 frames a second).
MAX_FRAMES = 3600
## The options a new preview shows (literal texts; "text:KEY" lines name texts of the manifest's tables).
NEW_ITEMS = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh"]
## The options of a yes / no preview without its own.
YES_NO_ITEMS = ["Yes", "No"]
## A new preview: the kind, its options, grid columns, list rows shown, the cursor, cancel, the key script.
NEW_PREVIEW = {"kind": "column", "columns": 2, "shown": 4, "cursor": 0, "cancel": True, "script": "down down a"}
## A stand-in arrow's size: pixels across its base and its height.
ARROW_BASE, ARROW_HEIGHT = 7, 4
## Pixels between the window's edge and a stand-in arrow.
ARROW_GAP = 1
## The menu answer a key script's word names: script word -> the pad's key name (asset_compiler MENU_KEY_NAMES).
SCRIPT_KEYS = {"a": "A", "b": "B", "select": "SELECT", "start": "START", "right": "RIGHT", "left": "LEFT", "up": "UP",
               "down": "DOWN", "r": "R", "l": "L", "x": "X", "y": "Y"}
## A key script's word that lets every key go for some frames.
WAIT_WORD = "wait"
## A held key's frames in a script word: `down*40`.
HOLD_MARK = "*"


# -- settings --------------------------------------------------------------------------------------------------------

@dataclass
class MenuField:
   """!One setting of a style's menu (a ui::MenuStyle member the compiler takes)."""

   ## The member's name.
   name: str
   ## "number", "word", "keys" (cancel_keys) or "sprite" (arrow_sprite).
   kind: str
   ## Lowest value (numbers).
   low: int = 0
   ## Highest value (numbers; the last word's index for a word).
   high: int = 0
   ## The words a word setting is written as (the manifest's), or the key names of cancel_keys.
   words: tuple[str, ...] = ()
   ## Its default: a number, a word, a list of keys, or None (no sprite, kNoCursor).
   default: Any = None
   ## menu.h's comment.
   doc: str = ""


def _header(name: str) -> str:
   """!An engine header's text (read again only when the file changed: a menu run asks for constants every frame).
   @param name  path below include/
   @return text ("" when it cannot be read)
   """
   try:
      path = engine.root() / "include" / name
      stamp = (str(path), path.stat().st_mtime_ns)
   except (OSError, engine.EngineNotFound):
      return ""
   if _HEADER_CACHE.get(name, (None, ""))[0] != stamp:
      try:
         _HEADER_CACHE[name] = (stamp, path.read_text(encoding="utf-8"))
      except OSError:
         return ""
   return _HEADER_CACHE[name][1]


## Header texts by name: (path and time, text).
_HEADER_CACHE: dict[str, tuple[tuple[str, int], str]] = {}
## header_constants() by header text.
_CONSTANTS_CACHE: dict[str, dict[str, int]] = {}


def header_constants(name: str = MENU_HEADER) -> dict[str, int]:
   """!The integer constants of an engine header.
   @param name  path below include/
   @return name -> value
   """
   text = _header(name)
   if text not in _CONSTANTS_CACHE:
      _CONSTANTS_CACHE[text] = {m.group("name"): int(m.group("value"), 0) for m in CONSTANT.finditer(text)}
   return _CONSTANTS_CACHE[text]


def _members() -> dict[str, tuple[str, str]]:
   """!MenuStyle's members in menu.h: name -> (default as written, comment).
   @return members
   """
   text = _header(MENU_HEADER)
   start = text.find("struct MenuStyle")
   end = text.find("\n};", start)   # the struct's own end (a member's `{};` is no end)
   out = {}
   for line in text[start:end].splitlines() if start >= 0 else []:
      m = MEMBER.match(line)
      if m is not None:
         out[m.group("name")] = ((m.group("default") or "").strip(), m.group("doc").strip())
   return out


def _no_cursor() -> int:
   """!kNoCursor: the end code (no cursor glyph).
   @return the code
   """
   return int(text_render.encoder().CODE_END)


def menu_fields() -> list[MenuField]:
   """!The settings of a style's menu: the compiler's (TEXT_BOX_MENU ranges, TEXT_BOX_MENU_NAMES words, cancel_keys
   over MENU_KEY_NAMES, arrow_sprite) in its MENU_ORDER, with menu.h's defaults and comments (worked out once per
   menu.h text).
   @return fields ([] for an engine before N3)
   """
   text = _header(MENU_HEADER)
   if text not in _FIELDS_CACHE:
      _FIELDS_CACHE[text] = _menu_fields()
   return list(_FIELDS_CACHE[text])


## menu_fields() by menu.h's text.
_FIELDS_CACHE: dict[str, list[MenuField]] = {}


def _menu_fields() -> list[MenuField]:
   """!menu_fields() worked out (no cache).
   @return fields
   """
   ac = engine.asset_compiler()
   ranges = dict(getattr(ac, "TEXT_BOX_MENU", {}))
   names = dict(getattr(ac, "TEXT_BOX_MENU_NAMES", {}))
   cpp = dict(getattr(ac, "TEXT_BOX_MENU_WORDS", {}))
   order = list(getattr(ac, "MENU_ORDER", ()))
   if not ranges or not order:
      return []
   members = _members()
   consts = header_constants()
   keys = tuple(getattr(ac, "MENU_KEY_NAMES", ()))
   out = []
   for name in order + [n for n in list(ranges) + list(names) if n not in order]:
      written, doc = members.get(name, ("", ""))
      if name in ranges:
         lo, hi = ranges[name]
         default: Any = consts.get(written, int(written, 0) if re.fullmatch(r"\d+|0[xX][0-9A-Fa-f]+", written)
                                   else 0)
         if name == "cursor" and written not in consts and not written.isdigit():
            default = None   # kNoCursor: no glyph
         out.append(MenuField(name, "number", lo, hi, (), default, doc))
      elif name in names:
         words = tuple(names[name])
         values = [consts.get(c) for c in cpp.get(name, ())]
         index = values.index(consts[written]) if written in consts and consts[written] in values else 0
         out.append(MenuField(name, "word", 0, len(words) - 1, words, words[index], doc))
      elif name == CANCEL_FIELD:
         out.append(MenuField(name, "keys", 0, 0, keys, [m.group("key") for m in KEY_DEFAULT.finditer(written)],
                              doc))
      elif name == SPRITE_FIELD:
         out.append(MenuField(name, "sprite", 0, 0, (), None, doc))
   return out


def field_of(name: str) -> MenuField | None:
   """!One menu setting.
   @param name  the member
   @return MenuField, or None
   """
   return next((f for f in menu_fields() if f.name == name), None)


def menu_of(style: JsonDict) -> JsonDict | None:
   """!A style's menu object.
   @param style  the style
   @return it (live), or None
   """
   found = style.get(MENU_KEY)
   return found if isinstance(found, dict) else None


def value(style: JsonDict, name: str) -> Any:
   """!A menu setting as written, else its default.
   @param style  the style
   @param name   the member
   @return a number, a word, a list of key names, a sprite key, or None
   """
   menu = menu_of(style) or {}
   f = field_of(name)
   if name in menu:
      return copy.deepcopy(menu[name])
   return copy.deepcopy(f.default) if f is not None else None


def numbers(style: JsonDict) -> dict[str, Any]:
   """!A style's menu as the engine's MenuStyle holds it: words as their menu.h constants, cancel_keys as key bits,
   the cursor kNoCursor when left out, arrow_sprite its key (or None).
   @param style  the style
   @return member -> value
   """
   ac = engine.asset_compiler()
   consts = header_constants()
   cpp = dict(getattr(ac, "TEXT_BOX_MENU_WORDS", {}))
   keys = list(getattr(ac, "MENU_KEY_NAMES", ()))
   out: dict[str, Any] = {}
   for f in menu_fields():
      v = value(style, f.name)
      if f.kind == "word":
         out[f.name] = consts.get(cpp[f.name][f.words.index(v)], f.words.index(v))
      elif f.kind == "keys":
         out[f.name] = key_bits(v or [], keys)
      elif f.kind == "number":
         out[f.name] = _no_cursor() if v is None else int(v)
      else:
         out[f.name] = v
   return out


def key_bits(names: Sequence[str], keys: Sequence[str] | None = None) -> int:
   """!Key bits of key names (hal::input::key_bit(): bit n for the compiler's MENU_KEY_NAMES[n]).
   @param names  key names
   @param keys   the pad's names in bit order, or None for the compiler's
   @return bits
   """
   order = list(keys) if keys is not None else list(getattr(engine.asset_compiler(), "MENU_KEY_NAMES", ()))
   bits = 0
   for n in names:
      if n in order:
         bits |= 1 << order.index(n)
   return bits


def has_menu(style: JsonDict) -> bool:
   """!Whether a style carries a menu.
   @param style  the style
   @return True when it does
   """
   return menu_of(style) is not None


def set_menu(doc: Document, key: str, on: bool) -> None:
   """!Gives a style a menu (every setting at its default) or takes it away (call inside Document.edit()).
   @param doc  asset manifest Document
   @param key  the style
   @param on   give it one
   @return None
   """
   style = text_boxes.find(doc, key)
   if on:
      style.setdefault(MENU_KEY, {})
   else:
      style.pop(MENU_KEY, None)


def set_value(doc: Document, key: str, name: str, v: Any) -> None:
   """!Changes one menu setting of a style (call inside Document.edit(); the style gets a menu if it has none).
   @param doc   asset manifest Document
   @param key   the style
   @param name  the member
   @param v     its value: a number in the compiler's range, a word, a list of key names, a sprite key
                ("sprite:NAME"), or None (left out: the default)
   @return None
   @throws DocumentError for an unknown setting or a value the engine refuses
   """
   f = field_of(name)
   if f is None:
      raise DocumentError(f"the engine's menu style has no setting {name!r}")
   menu = text_boxes.find(doc, key).setdefault(MENU_KEY, {})
   if v is None:
      menu.pop(name, None)
      return
   if f.kind == "number":
      if isinstance(v, bool) or not isinstance(v, int) or not f.low <= v <= f.high:
         raise DocumentError(f"menu {name} is {f.low}-{f.high}")
   elif f.kind == "word":
      if v not in f.words:
         raise DocumentError(f"menu {name} is one of {', '.join(f.words)}")
   elif f.kind == "keys":
      if not isinstance(v, list) or any(k not in f.words for k in v):
         raise DocumentError(f"menu {name} lists keys of {', '.join(f.words)}")
      v = [k for k in f.words if k in v]   # the pad's order, once each
   elif not isinstance(v, str) or not v.startswith("sprite:"):
      raise DocumentError(f"menu {name} names a sprite asset (sprite:NAME)")
   menu[name] = v


def preview_data(style: JsonDict) -> JsonDict:
   """!A style's menu preview settings (NEW_PREVIEW for those it leaves out).
   @param style  the style
   @return settings (a copy)
   """
   editor = style.get("editor")
   found = editor.get(PREVIEW_KEY) if isinstance(editor, dict) else None
   out = copy.deepcopy(NEW_PREVIEW)
   out["items"] = list(NEW_ITEMS)
   out["repeat"] = list(DEFAULT_REPEAT)
   if isinstance(found, dict):
      out.update(copy.deepcopy(found))
   return out


## The preview settings and what each holds.
PREVIEW_SETTINGS = {"kind": "one of KINDS", "items": "a list of option texts (text:KEY: a table's text)",
                    "columns": "grid columns (2 or more)", "option_width": "grid pixels per column (0: fitted)",
                    "shown": "list rows shown", "cursor": "the first option under the cursor",
                    "cancel": "a cancel key answers (true / false)", "script": "the keys (parse_script())",
                    "repeat": "[start, every] frames of the pad's repeat", "fit": "the window fitted to the options",
                    "x": "the window's column (cells)", "y": "its row"}


def set_preview(doc: Document, key: str, name: str, v: Any) -> None:
   """!Changes one menu preview setting of a style (its editor data; call inside Document.edit()).
   @param doc   asset manifest Document
   @param key   the style
   @param name  a PREVIEW_SETTINGS key
   @param v     its value, or None (left out)
   @return None
   @throws DocumentError for an unknown setting or a value of the wrong shape
   """
   if name not in PREVIEW_SETTINGS:
      raise DocumentError(f"a menu preview has no setting {name!r} ({', '.join(PREVIEW_SETTINGS)})")
   ok = v is None or {"kind": v in KINDS, "items": isinstance(v, list) and all(isinstance(t, str) for t in v),
                      "cancel": isinstance(v, bool), "fit": isinstance(v, bool), "script": isinstance(v, str),
                      "repeat": isinstance(v, list) and len(v) == len(DEFAULT_REPEAT) and
                      all(isinstance(n, int) and n >= 0 for n in v)}.get(name, isinstance(v, int) and
                                                                         not isinstance(v, bool) and v >= 0)
   if not ok:
      raise DocumentError(f"menu preview {name} is {PREVIEW_SETTINGS[name]}")
   if name == "script":
      parse_script(v)   # refused here rather than at run time
   style = text_boxes.find(doc, key)
   preview = style.setdefault("editor", {}).setdefault(PREVIEW_KEY, {})
   if v is None:
      preview.pop(name, None)
   else:
      preview[name] = v


def check_menu(style: JsonDict, font: JsonDict | None) -> list[str]:
   """!What a style's menu would draw wrongly (the compiler's refusals come with core.text_boxes.check()).
   @param style  the style
   @param font   its compiled font, or None (not checked)
   @return problems ("warning: ...")
   """
   if not has_menu(style) or not menu_fields():
      return []
   n = numbers(style)
   out = []
   if font is not None and n["cursor"] != _no_cursor() and not text_render.advance(font, n["cursor"]):
      out.append(f"warning: the menu's cursor glyph {n['cursor']} is not in the window's font (nothing is drawn)")
   if n["cursor"] != _no_cursor() and n["cursor_x"] + n["cursor_width"] > n["option_x"] and n["cursor_width"]:
      out.append(f"warning: a cursor move clears {n['cursor_width']} pixels from {n['cursor_x']}, into the options "
                 f"at {n['option_x']}")
   return out


# -- keys (src/ui/keys.cpp) ------------------------------------------------------------------------------------------

@dataclass
class Keys:
   """!One frame's keys (ui::Keys)."""

   ## Held this frame.
   held: int = 0
   ## Went down this frame.
   pressed: int = 0
   ## Went down, or held and repeated, this frame.
   repeated: int = 0


class KeyState:
   """!The pad between frames (ui::KeyState) and its repeat timing (ui::Repeat)."""

   def __init__(self, start: int = 0, every: int = 0) -> None:
      """!A pad with nothing held.
      @param start  frames the same keys are held before the first repeat (0: no repeat)
      @param every  frames between repeats after that
      """
      ## Frames before the first repeat.
      self.start = start
      ## Frames between repeats.
      self.every = every
      ## The keys held last frame.
      self.held = 0
      ## Frames left of the repeat counter.
      self.counter = 0

   def read(self, held: int) -> Keys:
      """!One frame's keys; the repeat counter runs (ui::read()).
      @param held  the keys held this frame
      @return Keys
      """
      k = Keys(held, held & ~self.held, held & ~self.held)
      if held != 0 and held == self.held and self.start != 0:
         # the same keys stay held: the counter runs; when it runs out every held key repeats this frame
         if self.counter > 0:
            self.counter -= 1
         if self.counter == 0:
            k.repeated = held
            self.counter = self.every
      else:
         self.counter = self.start   # none held, or the keys changed: the counter starts again
      self.held = held
      return k


def parse_script(text: str) -> list[int]:
   """!A key script: the keys held each frame. Words: a key (SCRIPT_KEYS: held PRESS_FRAMES frames, then let go as
   long), KEY*n (held n frames, then let go), `wait n` (nothing for n frames), keys joined by + act together
   (`up+a`).
   @param text  the script
   @return held key bits, one per frame (the frame after open() first)
   @throws DocumentError for a word that is no key
   """
   words = text.replace(",", " ").split()
   out: list[int] = []
   i = 0
   while i < len(words):
      w = words[i].lower()
      i += 1
      if w == WAIT_WORD:
         if i >= len(words) or not words[i].isdigit():
            raise DocumentError("wait takes a number of frames")
         out += [0] * int(words[i])
         i += 1
         continue
      held, _mark, count = w.partition(HOLD_MARK)
      if count and not count.isdigit():
         raise DocumentError(f"{w!r}: KEY*n holds a key n frames")
      names = held.split("+")
      if any(n not in SCRIPT_KEYS for n in names):
         raise DocumentError(f"{w!r}: the keys are {', '.join(SCRIPT_KEYS)} (KEY*n holds, wait n waits)")
      bits = key_bits([SCRIPT_KEYS[n] for n in names])
      frames = int(count) if count else PRESS_FRAMES
      out += [bits] * frames + [0] * PRESS_FRAMES
   return out


# -- the arrows' bounce (src/ui/arrows.cpp, capsule/core/trig.h) -----------------------------------------------------

def _trig() -> tuple[list[int], dict[str, int]]:
   """!trig.h's quarter-wave table and angle layout.
   @return (table, constants)
   """
   text = _header(TRIG_HEADER)
   m = SINE_TABLE.search(text)
   consts = dict(DEFAULT_TRIG)
   consts.update({k: v for k, v in header_constants(TRIG_HEADER).items() if k in DEFAULT_TRIG})
   table = [int(v) for v in m.group("values").replace("\n", " ").split(",") if v.strip()] if m else []
   return table, consts


def _toward_zero(a: int, b: int) -> int:
   """!C++ integer division (cut towards zero).
   @param a  dividend
   @param b  divisor
   @return a / b
   """
   q = abs(a) // abs(b)
   return q if (a < 0) == (b < 0) else -q


def bounce(amplitude: int, phase: int) -> int:
   """!One arrow's offset at a sine step (ui::bounce()): amplitude * sine / 256, the sine in 1/256 units, both cut
   towards zero.
   @param amplitude  pixels at the peak
   @param phase      sine step (256 a turn)
   @return pixels
   """
   table, c = _trig()
   if not table:
      return 0
   step = phase & (SINE_UNIT - 1)
   quadrant, i = step >> c["kQuadrantShift"], step & c["kQuarterStepMask"]
   v = table[c["kQuarterSteps"] - i] if quadrant & 1 else table[i]
   sine_q14 = -v if quadrant >= c["kNegativeQuadrant"] else v
   sine = _toward_zero(sine_q14, c["kQ14One"] // SINE_UNIT)
   return _toward_zero(sine * amplitude, SINE_UNIT)


# -- a menu (src/ui/menu.cpp) ----------------------------------------------------------------------------------------

@dataclass
class Options:
   """!What a menu shows (ui::Options)."""

   ## The options' codes.
   items: list[list[int]] = field(default_factory=list)
   ## The option the cursor starts on.
   cursor: int = 0
   ## A cancel key answers.
   cancel: bool = True
   ## More than 1: a grid of columns.
   columns: int = 1
   ## A grid's pixels per column.
   option_width: int = 0
   ## A list's rows shown (0: every option).
   shown: int = 0
   ## A list's first option shown.
   scroll: int = 0
   ## Frames before input is read, or None for the style's.
   delay: int | None = None


class Menu:
   """!A menu in a window (ui::Menu, open() / update() / move_to() of menu.cpp)."""

   def __init__(self, window: text_window.Window, style: dict[str, Any], options: Options,
                sound: Callable[[str, int], None]) -> None:
      """!Opens the menu (ui::open()): prints its options and cursor (a list plays its open sound).
      @param window   an open window
      @param style    numbers() of the style
      @param options  what it shows
      @param sound    called with (what, sound id) for each sound played
      """
      ## The window.
      self.w = window
      ## The style's numbers.
      self.s = style
      ## Plays a sound.
      self.sound_out = sound
      most = header_constants().get("kMaxItems", len(options.items))
      ## The options' codes.
      self.items = list(options.items)[:most]
      ## Options.
      self.count = len(self.items)
      ## Grid columns.
      self.columns = max(options.columns, 1)
      ## Grid rows.
      self.rows = self.count // self.columns
      ## A grid's column width.
      self.option_width = options.option_width if self.columns > 1 else 0
      ## Rows shown.
      self.shown = options.shown if self.columns == 1 and 0 < options.shown < self.count else self.count
      ## The option under the cursor.
      self.cursor = options.cursor if options.cursor < self.count else 0
      ## A list's first option shown.
      self.scroll = 0
      if self.is_list():
         last = self.count - self.shown
         self.scroll = min(options.scroll, last)
         self.cursor = self.scroll + (options.cursor if options.cursor < self.shown else 0)   # its row
      ## Frames left before input is read.
      self.delay = style["input_delay"] if options.delay is None else options.delay
      ## A cancel key answers.
      self.cancel = options.cancel
      c = header_constants()
      ## The cursor wraps.
      self.wrap = self.columns == 1 and not self.is_list() and (
         style["wrap"] == c.get("kWrapAlways") or (style["wrap"] == c.get("kWrapAbove") and
                                                   self.count > style["wrap_above"]))
      ## Shown.
      self.open = True
      self._draw_items(False)
      self._draw_cursor(self.cursor)
      if self.is_list():
         self._sound("open", style["sound_open"])

   def is_list(self) -> bool:
      """!A list: a column showing fewer options than it has.
      @return True for a list
      """
      return self.columns == 1 and self.shown < self.count

   def _sound(self, what: str, sound_id: int) -> None:
      """!Plays a sound unless it is kNoSound.
      @param what      move, choose, cancel or open
      @param sound_id  the sound
      @return None
      """
      if sound_id != header_constants().get("kNoSound", 0):
         self.sound_out(what, sound_id)

   def cursor_at(self, option: int) -> tuple[int, int]:
      """!Where the cursor of an option is drawn (a list: its row among the shown ones).
      @param option  the option
      @return (x, y) pixels in the window
      """
      index = option - self.scroll
      return (self.s["cursor_x"] + (index % self.columns) * self.option_width,
              self.s["top"] + (index // self.columns) * self.s["row_height"])

   def _draw_cursor(self, option: int) -> None:
      """!Draws the cursor glyph before an option.
      @param option  the option
      @return None
      """
      if self.s["cursor"] == _no_cursor():
         return
      x, y = self.cursor_at(option)
      self.w.print_at(x, y, [self.s["cursor"]])

   def _erase_cursor(self, option: int) -> None:
      """!Clears the cursor before an option (its rectangle back to the window's background).
      @param option  the option
      @return None
      """
      if self.s["cursor"] == _no_cursor():
         return
      x, y = self.cursor_at(option)
      self.w.fill(x, y, self.s["cursor_width"], self.s["cursor_height"], self.w.c.get("background", 0))

   def _draw_items(self, clear: bool) -> None:
      """!Prints the shown options.
      @param clear  clear their rows first (a list's scroll)
      @return None
      """
      if clear:
         top = self.s["top"]
         self.w.fill(0, top, self.w.width, self.w.height - top, self.w.c.get("background", 0))
      for i in range(min(self.shown, self.count - self.scroll)):
         x = self.s["option_x"] + (i % self.columns) * self.option_width
         y = self.s["top"] + (i // self.columns) * self.s["row_height"]
         self.w.print_at(x, y, self.items[self.scroll + i])

   def _list_step(self, down: bool) -> str:
      """!A list's move by one option, keeping the cursor near the middle of the shown rows (menu.cpp list_step()).
      @param down  moving down
      @return "none", "cursor" or "scrolled"
      """
      row = self.cursor - self.scroll
      shown = self.shown
      if not down:
         # the row the cursor stops at while the list can still scroll up: above the middle
         stop = 0 if shown == 1 else shown - (shown // HALF + shown % HALF) - 1
         if self.scroll == 0 or row > stop:
            if row == 0:
               return "none"
            self.cursor -= 1
            return "cursor"
         self.scroll -= 1
         self.cursor = self.scroll + stop
         return "scrolled"
      stop = 0 if shown == 1 else shown // HALF + shown % HALF
      if self.scroll == self.count - shown or row < stop:
         if row == shown - 1:
            return "none"
         self.cursor += 1
         return "cursor"
      self.scroll += 1
      self.cursor = self.scroll + stop
      return "scrolled"

   def _step(self, down: bool) -> bool:
      """!Moves a column's or a list's cursor one option.
      @param down  down (else up)
      @return True when the cursor moved
      """
      old = self.cursor
      if self.is_list():
         moved = self._list_step(down)
         if moved == "scrolled":
            self._draw_items(True)
            self._draw_cursor(self.cursor)
         elif moved == "cursor":
            self._erase_cursor(old)
            self._draw_cursor(self.cursor)
         return moved != "none"
      if down:
         self.cursor = self.cursor + 1 if self.cursor + 1 < self.count else (0 if self.wrap else self.cursor)
      else:
         self.cursor = self.cursor - 1 if self.cursor > 0 else (self.count - 1 if self.wrap else self.cursor)
      self._erase_cursor(old)
      self._draw_cursor(self.cursor)   # drawn again even when it stayed (the game redraws it)
      return self.cursor != old

   def _grid_step(self, dx: int, dy: int) -> bool:
      """!Moves a grid's cursor one cell (no wrap; a cell past the last option keeps it).
      @param dx  -1, 0 or 1
      @param dy  -1, 0 or 1
      @return True when the cursor moved
      """
      old = self.cursor
      pos = self.cursor
      col, row = pos % self.columns, pos // self.columns
      if dx and 0 <= col + dx < self.columns:
         pos += dx
      if dy and 0 <= row + dy < self.rows:
         pos += self.columns * dy
      if pos >= self.count:
         return False   # no such option: stays (and is not drawn again)
      self.cursor = pos
      self._erase_cursor(old)
      self._draw_cursor(self.cursor)
      return self.cursor != old

   def _move(self, dx: int, dy: int) -> None:
      """!Acts on a direction key.
      @param dx  -1, 0 or 1 (a grid)
      @param dy  -1 or 1, or 0 with dx
      @return None
      """
      moved = self._grid_step(dx, dy) if self.columns > 1 else self._step(dy > 0)
      if moved or (self.s["move_sound"] == header_constants().get("kSoundAlways") and not self.is_list()):
         self._sound("move", self.s["sound_move"])

   def _direction(self, k: Keys, key: str) -> bool:
      """!Whether a direction key acts this frame (on its press, or with kMoveRepeated on a repeat too).
      @param k    the frame's keys
      @param key  the key's name
      @return True when it acts
      """
      bit = key_bits([key])
      repeated = self.s["move_keys"] == header_constants().get("kMoveRepeated")
      return bool((k.repeated if repeated else k.pressed) & bit)

   def _answer_keys(self, k: Keys) -> tuple[bool, int]:
      """!Accept or cancel this frame.
      @param k  the frame's keys
      @return (the frame's input ended, the answer or NOTHING)
      """
      if k.pressed & key_bits(["A"]):
         self._sound("choose", self.s["sound_choose"])
         return True, self.cursor
      if k.pressed & self.s["cancel_keys"]:
         if self.cancel:
            self._sound("cancel", self.s["sound_cancel"])
            return True, CANCEL
         return True, NOTHING
      return False, NOTHING

   def update(self, k: Keys) -> int:
      """!One frame of the menu (ui::update()).
      @param k  the frame's keys
      @return the option chosen, CANCEL, or NOTHING
      """
      shown = self.open   # a local alias (Doxygen 1.12 reads `if not self.x:` as a new member)
      if not shown:
         return NOTHING
      if self.delay > 0:
         self.delay -= 1
         return NOTHING
      if self.s["order"] == header_constants().get("kEveryKey"):
         # each key acts in turn: Up, Down, then Accept (which ends the frame), then the cancel keys
         if self._direction(k, "UP"):
            self._move(0, -1)
         if self._direction(k, "DOWN"):
            self._move(0, 1)
         return self._answer_keys(k)[1]
      done, answer = self._answer_keys(k)
      if done:
         return answer
      for key, dx, dy, grid_only in (("UP", 0, -1, False), ("DOWN", 0, 1, False), ("LEFT", -1, 0, True),
                                     ("RIGHT", 1, 0, True)):
         if (not grid_only or self.columns > 1) and self._direction(k, key):
            self._move(dx, dy)
            break
      return NOTHING

   def move_to(self, option: int) -> None:
      """!Moves the cursor to an option (a list scrolls to show it); nothing is played (ui::move_to()).
      @param option  the option (past the last: ignored)
      @return None
      """
      shown = self.open   # a local alias (see update())
      if not shown or option >= self.count:
         return
      if self.is_list() and not self.scroll <= option < self.scroll + self.shown:
         self.scroll = min(option, self.count - self.shown)
         self.cursor = option
         self._draw_items(True)
         self._draw_cursor(self.cursor)
         return
      self._erase_cursor(self.cursor)
      self.cursor = option
      self._draw_cursor(self.cursor)


@dataclass
class ArrowState:
   """!A list's two scroll arrows (ui::Arrows): shown, and their offsets from their places."""

   ## The up arrow shows.
   up: bool = False
   ## The down arrow shows.
   down: bool = False
   ## The up arrow's offset, pixels.
   up_dy: int = 0
   ## The down arrow's offset.
   down_dy: int = 0


class Arrows:
   """!A list's scroll arrows as arrows.cpp runs them (no sprite: the preview draws stand-ins)."""

   def __init__(self, style: dict[str, Any]) -> None:
      """!Opens the arrows, hidden.
      @param style  numbers() of the style
      """
      ## The style's numbers.
      self.s = style
      ## The up arrow's sine step.
      self.up_phase = 0
      ## The down arrow's.
      self.down_phase = 0
      ## update() ran once.
      self.started = False
      ## What they show now.
      self.state = ArrowState()

   def update(self, scroll: int, last_scroll: int) -> ArrowState:
      """!One frame: shows the arrows the list can scroll towards, bobs them (ui::update()).
      @param scroll       the list's first shown option
      @param last_scroll  its scroll at the end
      @return the state after it
      """
      if not self.started:
         self.started = True   # the first frame starts the animations; the arrows stay hidden until the next
         return self.state
      amplitude, speed = self.s["arrow_amplitude"], self.s["arrow_speed"]
      self.state = ArrowState(scroll != 0, scroll != last_scroll, bounce(amplitude, self.up_phase),
                              bounce(amplitude, self.down_phase))
      self.up_phase = (self.up_phase + speed) % SINE_UNIT
      self.down_phase = (self.down_phase - speed) % SINE_UNIT   # the down arrow runs backwards
      return self.state


@dataclass
class MenuRun:
   """!A menu run frame by frame (run())."""

   ## The window's pixel size.
   size: tuple[int, int]
   ## The window's pixels after each frame (frame 0: after open()).
   frames: list[bytes] = field(default_factory=list)
   ## The cursor after each frame.
   cursors: list[int] = field(default_factory=list)
   ## A list's scroll after each frame.
   scrolls: list[int] = field(default_factory=list)
   ## The arrows after each frame (lists with an arrow sprite), else empty.
   arrows: list[ArrowState] = field(default_factory=list)
   ## What happened: (frame, text) (sounds, the answer).
   events: list[tuple[int, str]] = field(default_factory=list)
   ## The answer (an option, CANCEL) and its frame, or None.
   answer: tuple[int, int] | None = None
   ## The style with the window's geometry the run used (fitted).
   style: JsonDict = field(default_factory=dict)

   def frame_at(self, n: int) -> int:
      """!A frame clamped to the run.
      @param n  frame
      @return 0 to the last frame
      """
      frames = self.frames   # a local alias (Doxygen 1.12 reads a dataclass field used in a method as a new member)
      return min(max(n, 0), len(frames) - 1)


def text_width(font: JsonDict, codes: Sequence[int]) -> int:
   """!A text's first line in pixels (window::line_width(); S6b: text_window.line_width(), the engine's rule for
   Clear, SkipTo, ClearTo and MinSpacing).
   @param font   compiled font
   @param codes  the text
   @return pixels
   """
   return text_window.line_width(font, codes)


def kind_options(style: JsonDict, items: list[list[int]], font: JsonDict | None) -> Options:
   """!The Options of a style's preview kind.
   @param style  the style
   @param items  the options' codes
   @param font   its compiled font (a grid's fitted column width), or None
   @return Options
   """
   p = preview_data(style)
   kind = p.get("kind", KINDS[0])
   o = Options(items, int(p.get("cursor", 0)), bool(p.get("cancel", True)))
   if kind == "grid":
      o.columns = max(int(p.get("columns", 1)), 1)
      widest = max((text_width(font, c) for c in items), default=0) if font is not None else 0
      tile = text_boxes.limits().tile
      fitted = -(-(numbers(style)["option_x"] + widest) // tile) * tile   # whole cells
      o.option_width = int(p.get("option_width") or fitted)
   elif kind == "list":
      o.shown = int(p.get("shown", 0))
   return o


def fitted_style(style: JsonDict, options: Options, font: JsonDict | None) -> JsonDict:
   """!The style with the window the preview opens: its own, or fitted to the options (as a game sizes a menu box per
   menu: the widest option after option_x, the rows shown below top) when the preview says so (else when the style's
   window is a single cell).
   @param style    the style
   @param options  what the menu shows
   @param font     its compiled font, or None (no fit)
   @return a copy of the style (window x / y / width / height set)
   """
   out = copy.deepcopy(style)
   p = preview_data(style)
   window = out.setdefault("window", {})
   for k in ("x", "y"):
      if isinstance(p.get(k), int):
         window[k] = p[k]
   width, height = text_boxes.number(style, "window", "width"), text_boxes.number(style, "window", "height")
   fit = p.get("fit", width * height <= 1)
   if not fit or font is None or not options.items:
      return out
   n = numbers(style)
   tile = text_boxes.limits().tile
   columns = max(options.columns, 1)
   count = len(options.items)
   rows = options.shown if columns == 1 and 0 < options.shown < count else -(-count // columns)
   if columns > 1:
      across = n["option_x"] + options.option_width * columns
   else:
      across = n["option_x"] + max(text_width(font, c) for c in options.items)
   down = n["top"] + rows * max(n["row_height"], font["line_height"])
   window["width"], window["height"] = max(1, -(-across // tile)), max(1, -(-down // tile))
   return out


def run(style: JsonDict, font: JsonDict, items: list[list[int]], script: Sequence[int] | None = None,
        options: Options | None = None, base: Path | None = None,
        placeholders: dict[int, list[int]] | None = None, limit: int = MAX_FRAMES) -> MenuRun:
   """!Opens a style's menu in its window and runs it over a key script, frame by frame.
   @param style         the style (with a menu)
   @param font          its compiled font
   @param items         the options' codes
   @param script        held key bits per frame, or None for the preview's script (parse_script())
   @param options       what it shows, or None for the preview's kind (kind_options())
   @param base          the manifest's folder (the arrow image), or None
   @param placeholders  what field placeholders show, or None
   @param limit         most frames
   @return MenuRun
   """
   p = preview_data(style)
   o = options if options is not None else kind_options(style, items, font)
   if options is None:
      o.items = items
   geometry = fitted_style(style, o, font)
   n = numbers(style)
   w = text_window.Window(text_boxes.settings(geometry, base), font, None, placeholders)
   events: list[tuple[int, str]] = []
   frame = 0

   def sound(what: str, sound_id: int) -> None:
      """!Notes a sound."""
      events.append((frame, f"sound {sound_id} ({what})"))

   menu = Menu(w, n, o, sound)
   arrows = Arrows(n) if menu.is_list() and n.get(SPRITE_FIELD) else None
   state = KeyState(*[int(v) for v in p.get("repeat", DEFAULT_REPEAT)][:len(DEFAULT_REPEAT)])
   out = MenuRun((w.width, w.height), events=events, style=geometry)

   def keep() -> None:
      """!Keeps the frame's picture and state."""
      out.frames.append(bytes(w.pixels))
      out.cursors.append(menu.cursor)
      out.scrolls.append(menu.scroll)
      if arrows is not None:
         out.arrows.append(arrows.state)

   keep()
   keys = list(parse_script(str(p.get("script", ""))) if script is None else script)
   after = 0
   while frame < min(limit, len(keys)) and after <= AFTER_ANSWER:
      held = keys[frame]
      frame += 1
      k = state.read(held)
      if out.answer is None:
         answer = menu.update(k)
         if answer != NOTHING:
            out.answer = (answer, frame)
            events.append((frame, "cancel" if answer == CANCEL else f"chose option {answer}"))
            menu.open = False
      else:
         after += 1
      if arrows is not None:
         arrows.update(menu.scroll, menu.count - menu.shown)
      keep()
   return out


def describe(r: MenuRun) -> str:
   """!One line about a menu run: its frames and what happened.
   @param r  a run() result
   @return text
   """
   said = "; ".join(f"{f}: {t}" for f, t in r.events) or "nothing happened"
   return f"{len(r.frames) - 1} frames; {said}"


def preview(r: MenuRun, frame: int, base: Path | None = None) -> text_render.Canvas:
   """!A frame of a menu run on a 240x160 screen: the backdrop, the frame, the window and stand-in scroll arrows
   (triangles in the ink colour where the arrow sprite stands: above and below the window, centred).
   @param r      a run() result
   @param frame  the frame
   @param base   the manifest's folder (the frame image), or None
   @return a Canvas of the screen
   """
   style = r.style
   lim = text_boxes.limits()
   tile = lim.tile
   pens = text_boxes.pens(style)
   canvas = text_render.Canvas(lim.screen[0] * tile, lim.screen[1] * tile, pens.color(0))
   text_boxes.draw_frame(canvas, style, base)
   wx, wy = text_boxes.number(style, "window", "x") * tile, text_boxes.number(style, "window", "y") * tile
   rw, rh = r.size
   pixels = r.frames[r.frame_at(frame)]
   for y in range(rh):
      for x in range(rw):
         canvas.put(wx + x, wy + y, pens.color(pixels[y * rw + x]))
   if r.arrows:
      a = r.arrows[r.frame_at(frame)]
      cx = wx + rw // HALF
      ink = pens.color(pens.ink)
      if a.up:
         _triangle(canvas, cx, wy - ARROW_GAP - ARROW_HEIGHT + a.up_dy, True, ink)
      if a.down:
         _triangle(canvas, cx, wy + rh + ARROW_GAP + a.down_dy, False, ink)
   return canvas


def _triangle(canvas: text_render.Canvas, cx: int, top: int, up: bool, color: tuple[int, int, int]) -> None:
   """!A stand-in arrow: a small triangle pointing up or down.
   @param canvas  the screen
   @param cx      its middle column
   @param top     its top row
   @param up      pointing up
   @param color   its colour
   @return None
   """
   half = ARROW_BASE // HALF
   for r in range(ARROW_HEIGHT):
      span = r if up else ARROW_HEIGHT - 1 - r   # a row's half width grows towards the base
      for x in range(cx - min(span, half), cx + min(span, half) + 1):
         canvas.put(x, top + r, color)


def lines(style: JsonDict) -> list[str]:
   """!A style's menu as text (CLI `text-box menu show`).
   @param style  the style
   @return lines
   """
   if not has_menu(style):
      return [f"{style.get('key')}: no menu"]
   menu = menu_of(style) or {}
   out = [f"{style.get('key')}: menu"]
   for f in menu_fields():
      v = value(style, f.name)
      out.append(f"  {f.name} = {v}" + ("" if f.name in menu else " (default)"))
   return out
