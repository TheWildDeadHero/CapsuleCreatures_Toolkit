"""!Screen plans: a full-screen scene's video plan as data, previewed the way the GBA shows it
and exported as the C++ tables capsule/screen/screen.h takes.

A plan is a file NAME.screen.json (schema capsule.screen-plan/1, the studio's: the engine reads the C++ export(),
not the file) beside the asset manifest it draws from, or in its screens/ folder:

- "assets": the asset manifest, relative to the plan;
- "mode": the display mode (0-2);
- "layers": layers::LayerTemplate fields (bg, char_block, screen_block, screen_size, bpp8, priority, first_tile)
  plus what the preview loads: "tiles" (a tiles asset, at first_tile + tiles_offset), "tilemap" (a tilemap asset
  copied into the layer's map from tilemap_offset, as layers::set_tilemap()), "shown", scroll_x / scroll_y; "later"
  marks a template a screen applies after its setup with layers::init() (exported on its own, not in the Plan; the
  preview applies it with show_later);
- "palettes": colours loaded for the preview and named in the export: BG ones at a bank, OBJ ones under a palette tag
  (the first free bank, as screen::sprites::load_palette());
- "windows": text windows mirrored into a layer (layers::put_window(): w x h tiles from first_tile, in a bank),
  previewed as cleared windows (every pixel the fill index);
- "sheets": sprite tiles under a tag, first fit over the 1024 OBJ tiles: a tiles asset (sprites::load_sheet()) or
  "reserve" tiles left for the screen to write (sprites::reserve_sheet(), sprites::copy_tiles());
- "sprites": where sprites stand (centre x / y, shape, size, priority, subpriority, the sheet tile shown, flips);
- "steps": the screen's frame order (screen::Step);
- "transitions": open / in / out (screen::Transition): "none", "to_black", "from_black", "to_white", "from_white"
  or {"mask": "all" | "bg" | "obj" | number, "delay", "from", "to", "color"}; "fade_style" the FadeStyle (default the
  engine's kHandheldFade);
- the text windows and interactions "exit": how the screen leaves, {"call": "close" | "close_now" | "replace" |
"replace_now",
  "next": the replacing screen's plan name (replace / replace_now)}; left out: close(). close() plays the out fade
  and leaves the frame after its last call; close_now() (the screen faded itself) leaves at the end of the frame it
  is called in; replace() / replace_now() do the same and then start the next screen's setup instead of resuming
  what is below. exit_frames() lists the frames, the export writes a leave() helper that calls it.

A window holds no pixels of its own; the screen gives each window w x h tiles of its own memory
(a TileBuffer<W, H> member of its screen arena block, window::attach()). window_storage() and windows_storage() say
how many tiles and bytes each window and the whole plan take (the panel, describe() and the export show them).

check() finds what would go wrong on the GBA: a layer's map written over tiles (kind of overrun), layers the
mode has not, sheets or banks that do not fit, assets missing or of the wrong colour mode. render() simulates
background video memory (64 KB) and sprite memory: tiles, maps and windows are written where the plan puts them, so
an overlap shows as it would on the hardware, then the layers and sprites are composed in the GBA's priority order,
optionally at a step of a transition (fade_frames(): the engine's fade, call by call). export_cpp() writes a header
with the plan's tables (designated initializers, so every number is named by its field).

Functions that change a plan Document must run inside its edit(). Nothing here imports Qt.
"""
from __future__ import annotations

import copy
import functools
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import engine, screen_graphics as sg, text_window
from .document import Document, DocumentError
from .imaging import RGBA_BYTES
from .mapview import OPAQUE, TILE, bgr_to_rgb
from .preview import BLUE_SHIFT, CHANNEL_MASK, GREEN_SHIFT, HEIGHT, WIDTH

if TYPE_CHECKING:
   from .imaging import RgbaImage

## A parsed JSON object.
JsonDict = dict[str, Any]

## The schema of a plan file.
SCHEMA = "capsule.screen-plan/1"
## A plan file's suffix.
SUFFIX = ".screen.json"
## The folder beside the manifest new plans go to.
FOLDER = "screens"
## A new plan's path to its manifest (the plan in FOLDER, the manifest one up).
DEFAULT_ASSETS = "../assets.json"
## The plan's sections that are lists of items.
SECTIONS = ("layers", "palettes", "windows", "sheets", "sprites")
## A plan's C++ name: snake_case.
NAME = re.compile(r"[a-z][a-z0-9_]*")

## Background video memory in modes 0-2, bytes.
BG_VRAM = 0x10000
## Bytes of a character block and of a screen block.
CHAR_BLOCK_BYTES, SCREEN_BLOCK_BYTES = 0x4000, 0x800
## Character blocks and screen blocks.
CHAR_BLOCKS, SCREEN_BLOCKS = 4, 32
## Layers, display modes and priorities.
LAYERS, MODES, PRIORITIES = 4, 3, 4   # the GBA's (hal::video: kNumBgs, kModeAffine + 1, kNumPriorities)
## Highest tile number of a map entry and of a template's first tile.
MAX_TILE = sg.MAX_TILE
## Highest screen size (0 = 32x32, 1 = 64x32, 2 = 32x64, 3 = 64x64; affine: 16 << size square).
MAX_SCREEN_SIZE = 3
## Screen blocks a text-mode layer's map takes, by screen size.
SIZE_BLOCKS = (1, 2, 2, 4)
## Cells across and down a text-mode map, by screen size.
SIZE_CELLS = ((32, 32), (64, 32), (32, 64), (64, 64))
## Cells across an affine map of size 0 (each size doubles it).
AFFINE_BASE_CELLS = 16
## The affine layers of each display mode (mode 0 has none); a layer missing from LAYERS_OF a mode is off.
AFFINE_OF = {0: (), 1: (2,), 2: (2, 3)}
## The layers each display mode shows.
LAYERS_OF = {0: (0, 1, 2, 3), 1: (0, 1, 2), 2: (2, 3)}
## Sprite memory, 4bpp tiles.
OBJ_TILES = 1024
## Palette banks of sprite memory.
OBJ_BANKS = sg.BANKS
## Highest tag (0xFFFF is the engine's kNoTag).
MAX_TAG = 0xFFFE
## Highest subpriority.
MAX_SUBPRIORITY = 0xFF
## Range of a sprite's centre (int16, the OAM's 9-bit x / 8-bit y wrap is the engine's).
MIN_POS, MAX_POS = -0x8000, 0x7FFF
## Range of a layer's scroll offset (int16).
MIN_SCROLL, MAX_SCROLL = MIN_POS, MAX_POS
## Highest cell coordinate and size of a window (a 64 x 64 map).
MAX_WINDOW_CELLS = 64
## Most map entries a tilemap offset skips (a 64 x 64 map).
MAX_MAP_OFFSET = SCREEN_BLOCK_BYTES * max(SIZE_BLOCKS) // sg.ENTRY_BYTES
## Highest fill index of a window.
MAX_FILL = sg.NIBBLE_MASK
## The ways a screen leaves (screen.h close(), close_now(), replace(), replace_now()); the first is the
## default.
EXIT_CALLS = ("close", "close_now", "replace", "replace_now")
## The exits that start another screen in the closed one's place.
REPLACING = ("replace", "replace_now")
## The exits without the out fade (the screen faded itself; close_now() cancels any fade still running).
UNFADED = ("close_now", "replace_now")
## The keys of a plan's exit.
EXIT_KEYS = ("call", "next")
## Highest sprite size.
MAX_OBJ_SIZE = 3
## Prefix of the shapes' C++ names (hal::video::OBJ_SQUARE ...: the plan says "square").
SHAPE_PREFIX = "OBJ_"
## Prefix of the affine modes' C++ names (screen::sprites::kAffineOff ...: the plan says "off").
AFFINE_PREFIX = "kAffine"
## Prefix of an enum's count enumerator (NUM_STEPS ...), which is not a choice.
COUNT_PREFIX = "NUM_"
## The engine headers the plan's word lists come from (below include/).
SCREEN_H, SPRITES_H, FADE_H = "capsule/screen/screen.h", "capsule/screen/sprites.h", "capsule/screen/fade.h"
## The video and palette headers.
VIDEO_H, PALETTE_H = "capsule/hal/video.h", "capsule/gfx/palette.h"
## The preset transitions screen.h names, by the plan's preset word.
PRESET_NAMES = {"none": "kNoTransition", "to_black": "kFadeToBlack", "from_black": "kFadeFromBlack"}
## A CamelCase boundary (BuildOam -> build_oam).
CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
## The engine's sprite limit when its header cannot be read (screen::sprites::kMaxSprites).
DEFAULT_MAX_SPRITES = 64
## The engine's steps-a-frame limit when its header cannot be read (screen::kMaxSteps).
DEFAULT_MAX_STEPS = 8
## The three transitions of a screen.
TRANSITIONS = ("open", "in", "out")
## Blend amount of the loaded colours and of the fade colour (screen::fade kClear / kFull).
CLEAR, FULL = 0, 16
## The preset transitions: (from, to, colour); "none" is no fade.
PRESETS = {"none": None, "to_black": (CLEAR, FULL, "#000000"), "from_black": (FULL, CLEAR, "#000000"),
           "to_white": (CLEAR, FULL, "#f8f8f8"), "from_white": (FULL, CLEAR, "#f8f8f8")}
## Default transitions of a new plan (the reference games' usual: fade to black, set up, fade from black).
NEW_TRANSITIONS = {"open": "to_black", "in": "from_black", "out": "to_black"}
## Bank masks of a fade: every bank, the BG half, the OBJ half.
MASKS = {"all": 0xFFFFFFFF, "bg": 0x0000FFFF, "obj": 0xFFFF0000}
## Bits of the BG half of a mask (the OBJ half is above).
BG_MASK_BITS = OBJ_BANKS
## A fade's delay range (int8).
MIN_DELAY, MAX_DELAY = -0x80, 0x7F
## The fields of a fade style, in FadeStyle's order.
STYLE_FIELDS = ("step", "finish_calls", "alternate", "rounding")
## Most calls fade_frames() simulates (a fade with a long delay still ends long before).
MAX_FADE_CALLS = 4096
## OAM y wraps at this (8 bits); a sort key's y from 160 up counts as negative (build_oam()).
OAM_Y_WRAP = 256
## Bits of the subpriority in a sprite's sort key (priority << 8 | subpriority).
BITS_PER_PRIORITY_KEY = 8
## Halves a length (a sprite's centre to its corner).
HALF = 2
## How much bigger a double-size affine sprite's box is.
DOUBLE_BOX = 2
## Colour of a window outline and a sprite box in the preview's guides (RGBA).
GUIDE_COLOR = (255, 224, 0, 255)

## A field type: an integer range, a flag, a choice, an asset of a kind, a word.
INT, BOOL, CHOICE, ASSET, TEXT = "int", "bool", "choice", "asset", "text"


@dataclass(frozen=True)
class Field:
   """!One field of a plan section's items (the panel's forms and the command line are built from these)."""

   ## Its key.
   key: str
   ## INT, BOOL, CHOICE, ASSET or TEXT.
   kind: str
   ## A new item's value.
   default: Any
   ## What it is.
   help: str
   ## INT: lowest value.
   lo: int = 0
   ## INT: highest value.
   hi: int = 0
   ## CHOICE: the words; ASSET: (the asset kind,).
   choices: tuple[str, ...] = ()
   ## CHOICE: the engine list the words come from (engine_lists()), instead of choices.
   source: str = ""


## The fields of each section's items, in form order.
FIELDS: dict[str, tuple[Field, ...]] = {
   "layers": (
      Field("bg", INT, 0, "background layer", 0, LAYERS - 1),
      Field("char_block", INT, 0, "character block of its tiles (16 KB each)", 0, CHAR_BLOCKS - 1),
      Field("screen_block", INT, SCREEN_BLOCKS - 1, "first screen block of its map (2 KB each)", 0, SCREEN_BLOCKS - 1),
      Field("screen_size", INT, 0, "0 = 32x32 cells, 1 = 64x32, 2 = 32x64, 3 = 64x64 (affine: 16 << size square)",
            0, MAX_SCREEN_SIZE),
      Field("bpp8", BOOL, False, "8bpp tiles (an affine layer's always are)"),
      Field("priority", INT, 0, "0 is in front", 0, PRIORITIES - 1),
      Field("first_tile", INT, 0, "the tile loads and fills count from (the template's base tile)", 0, MAX_TILE),
      Field("tiles", ASSET, "", "tiles loaded into its character block (preview)", choices=("tiles",)),
      Field("tiles_offset", INT, 0, "first tile of the load, from first_tile", 0, MAX_TILE),
      Field("tilemap", ASSET, "", "tilemap copied into its map as stored (preview)", choices=("tilemap",)),
      Field("tilemap_offset", INT, 0, "first map entry the tilemap writes", 0, MAX_MAP_OFFSET),
      Field("shown", BOOL, True, "shown once set up (layers::show())"),
      Field("scroll_x", INT, 0, "scroll offset across, pixels", MIN_SCROLL, MAX_SCROLL),
      Field("scroll_y", INT, 0, "scroll offset down, pixels", MIN_SCROLL, MAX_SCROLL),
      Field("later", BOOL, False, "applied later with layers::init() (not part of the Plan)"),
   ),
   "palettes": (
      Field("palette", ASSET, "", "the palette asset", choices=("palette",)),
      Field("target", CHOICE, "bg", "BG palette memory at a bank, or OBJ memory under a tag",
            choices=("bg", "obj")),
      Field("bank", INT, 0, "BG: the first bank it loads into", 0, sg.MAX_BANK),
      Field("tag", INT, 0, "OBJ: its palette tag (the first free bank)", 0, MAX_TAG),
      Field("from_bank", INT, 0, "the asset's first bank loaded", 0, 2 * OBJ_BANKS - 1),
      Field("banks", INT, 1, "banks loaded (OBJ: one per tag)", 1, OBJ_BANKS),
   ),
   "windows": (
      Field("name", TEXT, "window", "its name (the export's)"),
      Field("bg", INT, 0, "the layer it is mirrored into", 0, LAYERS - 1),
      Field("x", INT, 1, "left column", 0, MAX_WINDOW_CELLS - 1),
      Field("y", INT, 1, "top row", 0, MAX_WINDOW_CELLS - 1),
      Field("w", INT, 8, "columns", 1, MAX_WINDOW_CELLS),
      Field("h", INT, 2, "rows", 1, MAX_WINDOW_CELLS),
      Field("first_tile", INT, 1, "its first tile in the layer's character block", 0, MAX_TILE),
      Field("palette", INT, 0, "its palette bank", 0, sg.MAX_BANK),
      Field("fill", INT, 1, "the colour index it is cleared to (preview)", 0, MAX_FILL),
   ),
   "sheets": (
      Field("tag", INT, 1, "its tile tag", 0, MAX_TAG),
      Field("tiles", ASSET, "", "4bpp tiles loaded (sprites::load_sheet())", choices=("tiles",)),
      Field("reserve", INT, 0, "or tiles reserved for the screen to write (sprites::reserve_sheet())", 0, OBJ_TILES),
   ),
   "sprites": (
      Field("name", TEXT, "sprite", "its name (the export's)"),
      Field("sheet", INT, 1, "its sheet's tag", 0, MAX_TAG),
      Field("palette_tag", INT, 0, "its palette's tag", 0, MAX_TAG),
      Field("shape", CHOICE, "square", "OBJ shape (hal::video::ObjShape)", source="shapes"),
      Field("size", INT, 1, "OBJ size 0-3 (with the shape: its pixels)", 0, MAX_OBJ_SIZE),
      Field("x", INT, WIDTH // 2, "centre x", MIN_POS, MAX_POS),
      Field("y", INT, HEIGHT // 2, "centre y", MIN_POS, MAX_POS),
      Field("priority", INT, 0, "0 is in front (over layers of the same priority)", 0, PRIORITIES - 1),
      Field("subpriority", INT, 0, "lower is in front among equal priorities", 0, MAX_SUBPRIORITY),
      Field("frame", INT, 0, "tile shown, from the sheet's first (an animation frame's value)", 0, OBJ_TILES - 1),
      Field("hflip", BOOL, False, "mirrored horizontally"),
      Field("vflip", BOOL, False, "mirrored vertically"),
      Field("mode", CHOICE, "normal", "drawing mode (hal::video::ObjMode)", source="modes"),
      Field("affine", CHOICE, "off", "affine mode (double: drawn in a box twice its size)", source="affine"),
   ),
}


class PlanError(DocumentError):
   """!A plan change the format refuses."""


@dataclass
class Problem:
   """!Something check() found."""

   ## "error" (the GBA shows it wrong, or the export would not compile) or "warning".
   severity: str
   ## Where: "layers 1", "sprites 0", "plan".
   where: str
   ## What.
   message: str

   def __str__(self) -> str:
      """!The problem as a line.
      @return text
      """
      return f"{self.severity}: {self.where}: {self.message}"


# -- the engine's lists ---------------------------------------------------------------------------------------------


def _header(name: str) -> str:
   """!An engine header's text.
   @param name  path below include/
   @return the text
   """
   return (engine.root() / "include" / name).read_text(encoding="utf-8")


def snake(name: str) -> str:
   """!A C++ name as the plan's word (BuildOam -> build_oam, OBJ_SQUARE -> square).
   @param name  the name
   @return snake_case
   """
   return CAMEL_BOUNDARY.sub("_", name).lower()


def enumerators(text: str, enum: str) -> list[str]:
   """!The enumerators of a C++ enum in a header (its count enumerator left out).
   @param text  the header
   @param enum  the enum's name
   @return the names, in order
   """
   m = re.search(r"enum\s+(?:class\s+)?" + re.escape(enum) + r"\b[^{;]*\{(?P<body>.*?)\};", text, re.DOTALL)
   if m is None:
      raise PlanError(f"the engine has no enum {enum} (an older engine?)")
   body = re.sub(r"///<[^\n]*|//[^\n]*", "", m.group("body"))
   names = [part.split("=")[0].strip() for part in body.split(",")]
   return [n for n in names if n and not n.startswith(COUNT_PREFIX)]


@functools.cache
def engine_lists() -> dict[str, dict[str, str]]:
   """!The word lists a plan uses, read from the engine (so a plan follows the engine's names): frame steps
   (screen::Step), OBJ shapes (hal::video::ObjShape), OBJ modes (ObjMode), affine modes (screen::sprites::kAffine*),
   blend roundings (gfx::palette::Rounding) and the preset transitions screen.h names; each plan word -> C++ name.
   @return {"steps", "shapes", "modes", "affine", "roundings", "presets"}
   """
   screen, video = _header(SCREEN_H), _header(VIDEO_H)
   out = {"steps": {snake(n): n for n in enumerators(screen, "Step")},
          "shapes": {snake(n[len(SHAPE_PREFIX):]): n for n in enumerators(video, "ObjShape")},
          "modes": {snake(n): n for n in enumerators(video, "ObjMode")},
          "roundings": {snake(n): n for n in enumerators(_header(PALETTE_H), "Rounding")},
          "affine": {snake(n[len(AFFINE_PREFIX):]): n
                     for n in re.findall(r"constexpr\s+uint8_t\s+(" + AFFINE_PREFIX + r"\w+)\s*=", _header(SPRITES_H))},
          "presets": {word: name for word, name in PRESET_NAMES.items() if re.search(r"\b" + name + r"\b", screen)}}
   return out


def choices_of(f: Field) -> tuple[str, ...]:
   """!A choice field's words.
   @param f  the field
   @return the words
   """
   return tuple(engine_lists()[f.source]) if f.source else f.choices


@functools.cache
def default_steps() -> list[str]:
   """!The engine's default frame (screen::kDefaultSteps), as plan words.
   @return the steps
   """
   m = re.search(r"kDefaultSteps\[\]\s*=\s*\{(?P<body>[^}]*)\}", _header(SCREEN_H))
   if m is None:
      raise PlanError("the engine has no screen::kDefaultSteps")
   return [snake(n.strip().split("::")[-1]) for n in m.group("body").split(",") if n.strip()]


@functools.cache
def handheld() -> JsonDict:
   """!The engine's kHandheldFade (screen/fade.h) as a fade style.
   @return {"step", "finish_calls", "alternate", "rounding"}
   """
   m = re.search(r"kHandheldFade\s*=\s*\{(?P<body>[^}]*)\}", _header(FADE_H))
   if m is None:
      raise PlanError("the engine has no screen::fade::kHandheldFade")
   step, finish, alternate, rounding = (v.strip() for v in m.group("body").split(","))
   return {"step": int(step), "finish_calls": int(finish), "alternate": alternate == "true",
           "rounding": snake(rounding.split("::")[-1])}


def obj_size(shape: str, size: int) -> tuple[int, int]:
   """!A sprite's pixels (the asset compiler's OBJ table: shape and size -> width, height).
   @param shape  a shape word
   @param size   0-3
   @return (width, height)
   """
   ac = engine.asset_compiler()
   index = ac.OBJ_SHAPE_NAMES.index(engine_lists()["shapes"][shape])
   for dims, (sh, sz) in ac.OBJ_SIZES.items():
      if (sh, sz) == (index, size):
         return dims
   raise PlanError(f"no OBJ size {size} of shape {shape}")


# -- files ---------------------------------------------------------------------------------------------------------


def limits() -> dict[str, int]:
   """!The engine's limits a plan meets (read from its headers).
   @return {"sprites", "steps"}
   """
   return {"sprites": engine.header_constant("capsule/screen/sprites.h", "kMaxSprites", DEFAULT_MAX_SPRITES),
           "steps": engine.header_constant("capsule/screen/screen.h", "kMaxSteps", DEFAULT_MAX_STEPS)}


def empty(name: str = "untitled", assets: str = DEFAULT_ASSETS) -> JsonDict:
   """!A new plan's data.
   @param name    its C++ name
   @param assets  its manifest, relative to the plan
   @return the plan
   """
   return {"schema": SCHEMA, "name": name, "assets": assets, "mode": 0, "layers": [], "palettes": [],
           "windows": [], "sheets": [], "sprites": [], "steps": default_steps(),
           "transitions": dict(NEW_TRANSITIONS)}


def plan_files(manifest: Document) -> list[Path]:
   """!The plans beside a manifest and in its screens/ folder that name it.
   @param manifest  asset manifest Document (saved)
   @return paths, sorted
   """
   if manifest.base_dir is None:
      return []
   out = []
   for folder in (manifest.base_dir, manifest.base_dir / FOLDER):
      for p in sorted(folder.glob("*" + SUFFIX)):
         try:
            data = json.loads(p.read_text(encoding="utf-8"))
         except (OSError, ValueError):
            continue
         if data.get("schema") == SCHEMA and (p.parent / str(data.get("assets", ""))).resolve() == manifest.path:
            out.append(p.resolve())
   return out


def create(manifest: Document, name: str) -> Document:
   """!A new plan file in the manifest's screens/ folder (written at once).
   @param manifest  asset manifest Document (saved)
   @param name      the plan's name (snake_case: the export's names)
   @return the plan Document
   """
   if manifest.path is None:
      raise PlanError("save the manifest first: a plan names it by its path")
   check_name(name)
   path = manifest.base_dir / FOLDER / (name + SUFFIX)
   if path.exists():
      raise PlanError(f"{path.name} exists")
   rel = Path("..") / manifest.path.name
   doc = Document(empty(name, rel.as_posix()), path, SCHEMA)
   path.parent.mkdir(parents=True, exist_ok=True)
   doc.save()
   return doc


def open_plan(path: str | Path) -> Document:
   """!Opens a plan file.
   @param path  NAME.screen.json
   @return Document
   """
   try:
      return Document.open(path, SCHEMA)
   except (OSError, ValueError) as e:
      raise PlanError(f"cannot read {path}: {e}") from e


def manifest_path(plan: Document) -> Path:
   """!The plan's asset manifest.
   @param plan  plan Document (saved)
   @return its path
   """
   if plan.path is None:
      raise PlanError("the plan has not been saved")
   return (plan.path.parent / str(plan.data.get("assets", DEFAULT_ASSETS))).resolve()


def check_name(name: object) -> None:
   """!Refuses a plan name the export cannot use.
   @param name  the name
   @return None
   """
   if not isinstance(name, str) or not NAME.fullmatch(name):
      raise PlanError(f"a plan's name is snake_case (letters, digits, _), got {name!r}")


# -- editing ---------------------------------------------------------------------------------------------------------


def field_of(section: str, key: str) -> Field:
   """!A section's field.
   @param section  one of SECTIONS
   @param key      the field
   @return it
   """
   for f in FIELDS[section]:
      if f.key == key:
         return f
   raise PlanError(f"{section} have no field {key!r} (known: {', '.join(f.key for f in FIELDS[section])})")


def value(item: JsonDict, section: str, key: str) -> Any:
   """!An item's field, or its default when the item leaves it out.
   @param item     the item
   @param section  its section
   @param key      the field
   @return the value
   """
   return item.get(key, field_of(section, key).default)


def coerce(section: str, key: str, raw: Any) -> Any:
   """!A field's value checked (text from the command line is converted).
   @param section  one of SECTIONS
   @param key      the field
   @param raw      the value
   @return the value to store
   """
   f = field_of(section, key)
   if f.kind == INT:
      if isinstance(raw, str):
         try:
            raw = int(raw, 0)
         except ValueError:
            raise PlanError(f"{key}: a number, got {raw!r}") from None
      if not isinstance(raw, int) or isinstance(raw, bool) or not f.lo <= raw <= f.hi:
         raise PlanError(f"{key}: {f.lo}-{f.hi}, got {raw!r}")
      return raw
   if f.kind == BOOL:
      if isinstance(raw, str):
         words = {"1": True, "true": True, "on": True, "yes": True, "0": False, "false": False, "off": False,
                  "no": False}
         if raw.lower() not in words:
            raise PlanError(f"{key}: on or off, got {raw!r}")
         raw = words[raw.lower()]
      if not isinstance(raw, bool):
         raise PlanError(f"{key}: true or false, got {raw!r}")
      return raw
   if f.kind == CHOICE:
      if raw not in choices_of(f):
         raise PlanError(f"{key}: one of {', '.join(choices_of(f))}, got {raw!r}")
      return raw
   if not isinstance(raw, str):
      raise PlanError(f"{key}: a word, got {raw!r}")
   if f.kind == ASSET and raw and not raw.startswith(sg.PREFIXES[f.choices[0]]):
      raise PlanError(f"{key}: a {f.choices[0]} key ({sg.PREFIXES[f.choices[0]]}NAME), got {raw!r}")
   if f.kind == TEXT and not NAME.fullmatch(raw):
      raise PlanError(f"{key}: snake_case (the export's names), got {raw!r}")
   return raw


def new_item(section: str, **fields: Any) -> JsonDict:
   """!A section item with the defaults, some fields given.
   @param section  one of SECTIONS
   @param fields   fields to set
   @return the item
   """
   item = {f.key: copy.deepcopy(f.default) for f in FIELDS[section]}
   for k, v in fields.items():
      item[k] = coerce(section, k, v)
   return item


def _section(plan: Document, section: str) -> list[JsonDict]:
   """!A section's list (made when missing).
   @param plan     plan Document
   @param section  one of SECTIONS
   @return the live list
   """
   if section not in SECTIONS:
      raise PlanError(f"no section {section!r} (known: {', '.join(SECTIONS)})")
   items = plan.data.setdefault(section, [])
   if not isinstance(items, list):
      raise PlanError(f"{section} is not a list; fix the file by hand")
   return items


def add_item(plan: Document, section: str, index: int | None = None, **fields: Any) -> int:
   """!Adds an item (call inside the plan's edit()).
   @param plan     plan Document
   @param section  one of SECTIONS
   @param index    position, or None for the end
   @param fields   its fields (the others get their defaults)
   @return its index
   """
   items = _section(plan, section)
   if section == "layers" and "bg" not in fields:
      taken = {value(it, "layers", "bg") for it in items if not value(it, "layers", "later")}
      fields["bg"] = next((b for b in range(LAYERS) if b not in taken), 0)
      fields.setdefault("screen_block", SCREEN_BLOCKS - 1 - fields["bg"])
   if section == "sheets" and "tag" not in fields:
      fields["tag"] = max([value(it, "sheets", "tag") for it in items] + [0]) + 1
   item = new_item(section, **fields)
   if index is None:
      items.append(item)
      return len(items) - 1
   items.insert(index, item)
   return index


def set_item(plan: Document, section: str, index: int, **fields: Any) -> None:
   """!Changes fields of an item (call inside the plan's edit()).
   @param plan     plan Document
   @param section  one of SECTIONS
   @param index    its index
   @param fields   the fields
   @return None
   """
   items = _section(plan, section)
   if not 0 <= index < len(items):
      raise PlanError(f"{section} has no item {index} (it has {len(items)})")
   checked = {k: coerce(section, k, v) for k, v in fields.items()}
   items[index].update(checked)


def remove_item(plan: Document, section: str, index: int) -> None:
   """!Removes an item (call inside the plan's edit()).
   @param plan     plan Document
   @param section  one of SECTIONS
   @param index    its index
   @return None
   """
   items = _section(plan, section)
   if not 0 <= index < len(items):
      raise PlanError(f"{section} has no item {index}")
   del items[index]


def move_item(plan: Document, section: str, index: int, delta: int) -> int:
   """!Moves an item up (-1) or down (+1) its list (the order things load and sprites are created in).
   @param plan     plan Document
   @param section  one of SECTIONS
   @param index    its index
   @param delta    -1 or +1
   @return its new index
   """
   items = _section(plan, section)
   to = index + delta
   if not 0 <= index < len(items) or not 0 <= to < len(items):
      return index
   items[index], items[to] = items[to], items[index]
   return to


def set_mode(plan: Document, mode: int) -> None:
   """!The display mode (call inside edit()).
   @param plan  plan Document
   @param mode  0-2
   @return None
   """
   if not isinstance(mode, int) or not 0 <= mode < MODES:
      raise PlanError(f"mode is 0-{MODES - 1}")
   plan.data["mode"] = mode


def set_name(plan: Document, name: str) -> None:
   """!The plan's name (the export's names; call inside edit()).
   @param plan  plan Document
   @param name  snake_case
   @return None
   """
   check_name(name)
   plan.data["name"] = name


def set_steps(plan: Document, steps: Sequence[str]) -> None:
   """!The screen's frame order (call inside edit()).
   @param plan   plan Document
   @param steps  step words (engine_lists()["steps"])
   @return None
   """
   known = engine_lists()["steps"]
   bad = [s for s in steps if s not in known]
   if bad:
      raise PlanError(f"unknown steps {', '.join(bad)} (known: {', '.join(known)})")
   most = limits()["steps"]
   if len(steps) > most:
      raise PlanError(f"{len(steps)} steps; a screen's frame has at most {most}")
   plan.data["steps"] = list(steps)


def transition(plan: Document | JsonDict, which: str) -> Any:
   """!One of the plan's transitions as stored.
   @param plan   plan Document or data
   @param which  open, in or out
   @return a preset word or a fade object
   """
   data = plan.data if isinstance(plan, Document) else plan
   return data.get("transitions", {}).get(which, NEW_TRANSITIONS[which])


def fade_of(value_: Any) -> JsonDict | None:
   """!A transition as a fade object, or None for no fade.
   @param value_  a preset word or a fade object
   @return {"mask", "delay", "from", "to", "color"} (mask a number), or None
   """
   if isinstance(value_, str):
      if value_ not in PRESETS:
         raise PlanError(f"transition {value_!r}: one of {', '.join(PRESETS)} or a fade object")
      if PRESETS[value_] is None:
         return None
      start, end, color = PRESETS[value_]
      return {"mask": MASKS["all"], "delay": 0, "from": start, "to": end, "color": color}
   if not isinstance(value_, dict):
      raise PlanError("a transition is a preset word or a fade object")
   unknown = set(value_) - {"mask", "delay", "from", "to", "color"}
   if unknown:
      raise PlanError(f"a fade has no {', '.join(sorted(unknown))}")
   mask = value_.get("mask", "all")
   if isinstance(mask, str):
      if mask not in MASKS:
         raise PlanError(f"mask: one of {', '.join(MASKS)} or a number")
      mask = MASKS[mask]
   if not isinstance(mask, int) or isinstance(mask, bool) or not 0 <= mask <= MASKS["all"]:
      raise PlanError("mask: a 32-bit bank mask (bits 0-15 BG, 16-31 OBJ)")
   delay = value_.get("delay", 0)
   if not isinstance(delay, int) or not MIN_DELAY <= delay <= MAX_DELAY:
      raise PlanError(f"delay: {MIN_DELAY}-{MAX_DELAY}")
   ends = []
   for k, default in (("from", CLEAR), ("to", FULL)):
      v = value_.get(k, default)
      if not isinstance(v, int) or isinstance(v, bool) or not CLEAR <= v <= FULL:
         raise PlanError(f"{k}: {CLEAR}-{FULL}")
      ends.append(v)
   color = value_.get("color", "#000000")
   sg.to_bgr555(color)
   return {"mask": mask, "delay": delay, "from": ends[0], "to": ends[1], "color": color}


def set_transition(plan: Document, which: str, value_: Any) -> None:
   """!One transition (call inside edit()).
   @param plan    plan Document
   @param which   open, in or out
   @param value_  a preset word or a fade object
   @return None
   """
   if which not in TRANSITIONS:
      raise PlanError(f"transitions are {', '.join(TRANSITIONS)}")
   fade_of(value_)
   plan.data.setdefault("transitions", dict(NEW_TRANSITIONS))[which] = value_


def fade_style(plan: Document | JsonDict) -> JsonDict:
   """!The plan's fade style (the engine's kHandheldFade unless it gives its own).
   @param plan  plan Document or data
   @return {"step", "finish_calls", "alternate", "rounding"}
   """
   data = plan.data if isinstance(plan, Document) else plan
   style = dict(handheld())
   style.update(data.get("fade_style") or {})
   return style


def set_fade_style(plan: Document, style: JsonDict | None) -> None:
   """!The plan's fade style (None: the engine's kHandheldFade; call inside edit()).
   @param plan   plan Document
   @param style  {"step", "finish_calls", "alternate", "rounding"} (each optional), or None
   @return None
   """
   if style is None:
      plan.data.pop("fade_style", None)
      return
   base = handheld()
   merged = dict(base)
   merged.update(style)
   if set(merged) != set(STYLE_FIELDS):
      raise PlanError(f"a fade style has {', '.join(STYLE_FIELDS)}")
   for k in ("step", "finish_calls"):
      if not isinstance(merged[k], int) or isinstance(merged[k], bool) or not 0 <= merged[k] <= FULL:
         raise PlanError(f"{k}: 0-{FULL}")
   roundings = engine_lists()["roundings"]
   if not isinstance(merged["alternate"], bool) or merged["rounding"] not in roundings:
      raise PlanError(f"alternate is true / false; rounding {' or '.join(roundings)}")
   plan.data["fade_style"] = {k: v for k, v in merged.items() if base[k] != v} or None
   if plan.data["fade_style"] is None:
      del plan.data["fade_style"]


# -- The exit --------------------------------------------------------------------------------------


def exit_of(plan: Document | JsonDict) -> JsonDict:
   """!how the screen leaves, as stored (close() when the plan says nothing).
   @param plan  plan Document or data
   @return {"call": one of EXIT_CALLS, "next": a plan name or ""}
   """
   data = plan.data if isinstance(plan, Document) else plan
   raw = data.get("exit")
   raw = raw if isinstance(raw, dict) else {}
   return {"call": raw.get("call", EXIT_CALLS[0]), "next": raw.get("next", "") or ""}


def _check_exit(raw: Any) -> None:
   """!an exit the plan may keep.
   @param raw  the "exit" value
   @return None
   @throws PlanError when it is malformed, or the engine lacks the call
   """
   if not isinstance(raw, dict) or set(raw) - set(EXIT_KEYS):
      raise PlanError(f"an exit is {{{', '.join(EXIT_KEYS)}}}")
   call = raw.get("call", EXIT_CALLS[0])
   if call not in EXIT_CALLS:
      raise PlanError(f"exit call {call!r}: one of {', '.join(EXIT_CALLS)}")
   if not re.search(r"\bvoid\s+" + call + r"\s*\(", _header(SCREEN_H)):
      raise PlanError(f"the engine's screen.h has no {call}() (it came with a newer engine)")
   nxt = raw.get("next", "")
   if nxt and (not isinstance(nxt, str) or not NAME.fullmatch(nxt)):
      raise PlanError(f"exit next {nxt!r}: a plan's snake_case name")


def set_exit(plan: Document, call: str, next_screen: str = "") -> None:
   """!how the screen leaves (call inside edit()); close() with no next screen leaves the key out.
   @param plan         plan Document
   @param call         one of EXIT_CALLS
   @param next_screen  replace / replace_now: the next screen's plan name ("" for none yet)
   @return None
   """
   raw = {"call": call, "next": next_screen if call in REPLACING else ""}
   _check_exit(raw)
   if call == EXIT_CALLS[0]:
      plan.data.pop("exit", None)
      return
   plan.data["exit"] = {k: v for k, v in raw.items() if v}


def out_calls(plan: JsonDict) -> int:
   """!calls the out fade makes (fade_frames() of the out transition; 0 for none).
   @param plan  plan data
   @return calls
   """
   return len(fade_frames(fade_of(transition(plan, "out")), fade_style(plan)))


def exit_frames(plan: JsonDict, below: str = "what is below") -> list[tuple[int, str]]:
   """!The frames the plan's exit takes, counted from the frame its call is made in (0; a call
   between frames counts as the frame that just ended): close() / replace() run the out fade (its first call at the
   call, one a frame after), the screen leaves (Screen::leave(false)) the frame after the last call and what comes
   next starts the frame after that; close_now() / replace_now() leave at the end of the frame they are called in
   (its other steps still run) and what comes next starts the next frame, the reference games' SetMainCallback2
   frame and the next callback's first.
   @param plan   plan data
   @param below  what resumes when the screen closes (a screen's name, or the field)
   @return [(frame, what happens)]
   """
   ex = exit_of(plan)
   call = ex["call"]
   nxt = ex["next"] or "the next screen"
   then = f"{nxt}'s setup makes its first call (what is below stays given up)" if call in REPLACING else \
      f"{below} resumes (a screen's setup again with resumed = true, or the field's Host::resume steps)"
   if call in UNFADED:
      return [(0, f"{call}(): no out fade; the frame's other steps run, the screen leaves at its end"),
              (1, then)]
   calls = out_calls(plan)
   out: list[tuple[int, str]] = []
   if calls:
      out.append((0, f"{call}(): the out fade's first call ({calls} calls, one a frame)"))
      if calls > 1:
         out.append((calls - 1, "the out fade's last call"))
   else:
      out.append((0, f"{call}(): no out fade (out is none)"))
   out.append((calls if calls else 1, "the screen leaves (Screen::leave(false)); nothing else runs"))
   out.append(((calls if calls else 1) + 1, then))
   return out


# -- Window storage -------------------------------------------------------------------------------


def window_storage(item: JsonDict) -> text_window.Storage:
   """!The tiles a plan window needs from its screen (window::attach(): its w x h cells).
   @param item  a windows item
   @return text_window.Storage
   """
   return text_window.storage(value(item, "windows", "w"), value(item, "windows", "h"))


def windows_storage(plan: JsonDict) -> tuple[int, int]:
   """!The window buffers of the whole plan (what its arena block holds for them).
   @param plan  plan data
   @return (tiles, bytes)
   """
   found = [window_storage(w) for w in plan.get("windows", [])]
   return sum(st.tiles for st in found), sum(st.size_bytes for st in found)


# -- what the plan uses ----------------------------------------------------------------------------------------------


def active_layers(plan: JsonDict, later: bool = False) -> dict[int, JsonDict]:
   """!The layer each BG index has: the Plan's, or with @p later the templates applied later replacing them.
   @param plan   plan data
   @param later  apply the "later" templates (layers::init()) too
   @return {bg: layer item}
   """
   out: dict[int, JsonDict] = {}
   for lay in plan.get("layers", []):
      if not value(lay, "layers", "later"):
         out[value(lay, "layers", "bg")] = lay
   if later:
      for lay in plan.get("layers", []):
         if value(lay, "layers", "later"):
            out[value(lay, "layers", "bg")] = lay
   return out


def is_affine(mode: int, bg: int) -> bool:
   """!Whether a layer is affine in a display mode.
   @param mode  0-2
   @param bg    0-3
   @return True for mode 1's BG2 and mode 2's BG2 / BG3
   """
   return bg in AFFINE_OF.get(mode, ())


def map_cells(lay: JsonDict, mode: int) -> tuple[int, int]:
   """!Cells across and down a layer's map.
   @param lay   layer item
   @param mode  display mode
   @return (across, down)
   """
   size = value(lay, "layers", "screen_size")
   if is_affine(mode, value(lay, "layers", "bg")):
      n = AFFINE_BASE_CELLS << size
      return n, n
   return SIZE_CELLS[size]


def map_bytes(lay: JsonDict, mode: int) -> int:
   """!Bytes a layer's map takes.
   @param lay   layer item
   @param mode  display mode
   @return bytes
   """
   if is_affine(mode, value(lay, "layers", "bg")):
      w, h = map_cells(lay, mode)
      return w * h
   return SIZE_BLOCKS[value(lay, "layers", "screen_size")] * SCREEN_BLOCK_BYTES


def tile_bytes_of(lay: JsonDict, mode: int) -> int:
   """!Bytes of one of a layer's tiles.
   @param lay   layer item
   @param mode  display mode
   @return 32 or 64
   """
   eight = value(lay, "layers", "bpp8") or is_affine(mode, value(lay, "layers", "bg"))
   return sg.TILE_BYTES_8BPP if eight else sg.TILE_BYTES_4BPP


def cell_index(lay: JsonDict, mode: int, x: int, y: int) -> int:
   """!A cell's entry index in a layer's map, through its size (layers::cell_index(): a wide map's right half is
   the next screen block).
   @param lay   layer item
   @param mode  display mode
   @param x     column (wraps)
   @param y     row (wraps)
   @return the index
   """
   w, h = map_cells(lay, mode)
   x, y = x % w, y % h
   if is_affine(mode, value(lay, "layers", "bg")):
      return y * w + x
   block_cells = sg.ROW_CELLS * sg.ROW_CELLS
   blocks_across = w // sg.ROW_CELLS
   block = (y // sg.ROW_CELLS) * blocks_across + x // sg.ROW_CELLS
   return block * block_cells + (y % sg.ROW_CELLS) * sg.ROW_CELLS + x % sg.ROW_CELLS


class Assets:
   """!The compiled assets a plan names (compiled once per check / render)."""

   def __init__(self, manifest: Document) -> None:
      """!Starts empty.
      @param manifest  the asset manifest Document
      """
      ## The manifest.
      self.manifest = manifest
      ## key -> compiled record, or None (missing, or not compiling).
      self._cache: dict[str, JsonDict | None] = {}
      ## key -> why it is not there.
      self.errors: dict[str, str] = {}

   def get(self, key: str, kind: str) -> JsonDict | None:
      """!A compiled asset of a kind.
      @param key   its key
      @param kind  tiles, tilemap or palette
      @return the record, or None (errors says why)
      """
      if not key:
         return None
      if key not in self._cache:
         a = self.manifest.find(key)
         rec = None
         if a is None:
            self.errors[key] = "no such asset in the manifest"
         elif a.get("kind") != kind:
            self.errors[key] = f"is a {a.get('kind')}, not a {kind}"
         else:
            r = self.manifest.compile_asset(a)
            rec = r.compiled if r.ok else None
            if rec is None:
               self.errors[key] = r.error or "does not compile"
         self._cache[key] = rec
      return self._cache[key]


@dataclass
class Region:
   """!Bytes of background video memory a plan writes."""

   ## Who: "BG1 tiles (tiles:X)", "BG0 map", "window title tiles".
   owner: str
   ## "tiles" or "map".
   kind: str
   ## First byte.
   start: int
   ## One past the last.
   end: int
   ## The layer.
   bg: int
   ## What it loads (asset key or window name), so the same load twice is not a clash.
   source: str


def regions(plan: JsonDict, assets: Assets, later: bool = False) -> list[Region]:
   """!The parts of background video memory each layer's tiles, map and windows take, in the order they are written.
   @param plan    plan data
   @param assets  the compiled assets
   @param later   with the later templates applied
   @return regions
   """
   mode = plan.get("mode", 0)
   out = []
   for bg, lay in sorted(active_layers(plan, later).items()):
      cb, tb = value(lay, "layers", "char_block"), tile_bytes_of(lay, mode)
      base = cb * CHAR_BLOCK_BYTES + value(lay, "layers", "first_tile") * tb
      rec = assets.get(value(lay, "layers", "tiles"), "tiles")
      if rec is not None:
         start = base + value(lay, "layers", "tiles_offset") * tb
         out.append(Region(f"BG{bg} tiles ({lay['tiles']})", "tiles", start, start + rec["count"] * tb, bg,
                           lay["tiles"]))
      for w in plan.get("windows", []):
         if value(w, "windows", "bg") == bg:
            start = cb * CHAR_BLOCK_BYTES + value(w, "windows", "first_tile") * tb
            n = value(w, "windows", "w") * value(w, "windows", "h")
            out.append(Region(f"window {value(w, 'windows', 'name')} tiles (BG{bg})", "tiles", start,
                              start + n * tb, bg, "window:" + str(value(w, "windows", "name"))))
      start = value(lay, "layers", "screen_block") * SCREEN_BLOCK_BYTES
      out.append(Region(f"BG{bg} map", "map", start, start + map_bytes(lay, mode), bg, f"map{bg}"))
   return out


def _span(r: Region) -> str:
   """!A region's bytes as text.
   @param r  the region
   @return "0x8000-0x87FF"
   """
   return f"0x{r.start:04X}-0x{r.end - 1:04X}"


def check(plan: JsonDict, manifest: Document | None, later: bool = False) -> list[Problem]:
   """!What would go wrong on the GBA, or in the export.
   @param plan      plan data
   @param manifest  its asset manifest Document, or None (asset checks are skipped)
   @param later     check with the later templates applied too
   @return problems (errors first)
   """
   out: list[Problem] = []
   mode = plan.get("mode", 0)
   if not isinstance(plan.get("name"), str) or not NAME.fullmatch(plan["name"]):
      out.append(Problem("error", "plan", f"name {plan.get('name')!r} is not snake_case"))
   if mode not in LAYERS_OF:
      out.append(Problem("error", "plan", f"mode {mode!r}: 0-{MODES - 1}"))
      return out
   for section in SECTIONS:
      for i, item in enumerate(plan.get(section, [])):
         for k, v in item.items():
            try:
               coerce(section, k, v)
            except PlanError as e:
               out.append(Problem("error", f"{section} {i}", str(e)))
   for section in ("windows", "sprites"):
      names: dict[str, int] = {}
      for i, item in enumerate(plan.get(section, [])):
         n = value(item, section, "name")
         if n in names:
            out.append(Problem("error", f"{section} {i}", f"the name {n!r} is {section} {names[n]}'s too (the "
                                                          "export names a constant after it)"))
         names.setdefault(n, i)
   seen_bg: dict[int, int] = {}
   for i, lay in enumerate(plan.get("layers", [])):
      bg, where = value(lay, "layers", "bg"), f"layers {i}"
      if not value(lay, "layers", "later"):
         if bg in seen_bg:
            out.append(Problem("error", where, f"BG{bg} is in the plan twice (layers {seen_bg[bg]} and {i})"))
         seen_bg[bg] = i
      if bg not in LAYERS_OF[mode]:
         out.append(Problem("error", where, f"mode {mode} has no BG{bg} (it shows BG"
                                            f"{', BG'.join(str(b) for b in LAYERS_OF[mode])})"))
      if is_affine(mode, bg) and not value(lay, "layers", "bpp8"):
         out.append(Problem("warning", where, f"BG{bg} is affine in mode {mode}: its tiles are 8bpp (bpp8 on)"))
   try:
      steps, known = plan.get("steps", default_steps()), engine_lists()["steps"]
      if any(s not in known for s in steps) or len(steps) > limits()["steps"]:
         out.append(Problem("error", "steps", f"steps are at most {limits()['steps']} of {', '.join(known)}"))
   except TypeError:
      out.append(Problem("error", "steps", "steps is a list of words"))
   for which in TRANSITIONS:
      try:
         fade_of(transition(plan, which))
      except PlanError as e:
         out.append(Problem("error", f"transition {which}", str(e)))
   out += _exit_problems(plan, manifest)
   for i, w in enumerate(plan.get("windows", [])):
      st = window_storage(w)
      if not st.fits():   # TileBuffer<W, H> and window::open() take 1 to kMaxTiles cells
         out.append(Problem("error", f"windows {i}", f"it covers {st.tiles} cells; a window has at most "
                                                     f"{st.max_tiles} tiles (window::kMaxTiles)"))
   if manifest is not None:
      out += _asset_problems(plan, Assets(manifest), later)
   out.sort(key=lambda p: p.severity != "error")
   return out


def _exit_problems(plan: JsonDict, manifest: Document | None) -> list[Problem]:
   """!what is wrong with the plan's exit.
   @param plan      plan data
   @param manifest  its asset manifest Document (the plans beside it), or None
   @return problems
   """
   if "exit" in plan:
      try:
         _check_exit(plan["exit"])
      except PlanError as e:
         return [Problem("error", "exit", str(e))]
   ex = exit_of(plan)
   out = []
   try:
      calls = out_calls(plan)
   except PlanError:
      calls = 0   # the transition's own problem is reported
   if ex["call"] in UNFADED and calls:
      out.append(Problem("warning", "exit", f"{ex['call']}() never plays the out fade ({calls} calls): the screen "
                                            "must fade itself first (or set out to none, or leave with close())"))
   if ex["call"] in REPLACING and not ex["next"]:
      out.append(Problem("warning", "exit", f"{ex['call']}() names no next screen"))
   elif ex["call"] in REPLACING and manifest is not None:
      names = set()
      for path in plan_files(manifest):
         try:
            names.add(json.loads(path.read_text(encoding="utf-8")).get("name"))
         except (OSError, ValueError, AttributeError):
            continue
      if ex["next"] not in names:
         out.append(Problem("warning", "exit", f"next screen {ex['next']!r} is no plan beside the manifest"))
   return out


def _asset_problems(plan: JsonDict, assets: Assets, later: bool) -> list[Problem]:
   """!check()'s part that needs the compiled assets: video memory, colour modes, sheets, banks, sprites.
   @param plan    plan data
   @param assets  the compiled assets
   @param later   with the later templates applied
   @return problems
   """
   out: list[Problem] = []
   mode = plan.get("mode", 0)
   for i, lay in enumerate(plan.get("layers", [])):
      where, bg = f"layers {i}", value(lay, "layers", "bg")
      rec = assets.get(value(lay, "layers", "tiles"), "tiles")
      if lay.get("tiles") and rec is None:
         out.append(Problem("error", where, f"{lay['tiles']}: {assets.errors.get(lay['tiles'])}"))
      eight = value(lay, "layers", "bpp8") or is_affine(mode, bg)
      if rec is not None and (rec["bpp"] == sg.BPP8) != bool(eight):
         out.append(Problem("error", where, f"{lay['tiles']} is {rec['bpp']}bpp; BG{bg} takes "
                                            f"{sg.BPP8 if eight else sg.BPP4}bpp tiles"))
      mp = assets.get(value(lay, "layers", "tilemap"), "tilemap")
      if lay.get("tilemap") and mp is None:
         out.append(Problem("error", where, f"{lay['tilemap']}: {assets.errors.get(lay['tilemap'])}"))
      if mp is not None:
         if mp["affine"] != is_affine(mode, bg):
            out.append(Problem("error", where, f"{lay['tilemap']} is {'an affine' if mp['affine'] else 'a text'} "
                                               f"map; BG{bg} is {'affine' if is_affine(mode, bg) else 'a text'} "
                                               f"layer in mode {mode}"))
         w, h = map_cells(lay, mode)
         room = w * h - value(lay, "layers", "tilemap_offset")
         if mp["count"] > room:
            out.append(Problem("warning", where, f"{lay['tilemap']} has {mp['count']} entries; the map has room for "
                                                 f"{max(room, 0)} from entry {lay.get('tilemap_offset', 0)} (the rest "
                                                 "is not copied)"))
   for i, w in enumerate(plan.get("windows", [])):
      where, bg = f"windows {i}", value(w, "windows", "bg")
      lay = active_layers(plan, later).get(bg)
      if lay is None:
         out.append(Problem("error", where, f"BG{bg} is not in the plan"))
         continue
      cw, ch = map_cells(lay, mode)
      if value(w, "windows", "x") + value(w, "windows", "w") > cw or value(w, "windows", "y") + \
            value(w, "windows", "h") > ch:
         out.append(Problem("error", where, f"it goes past BG{bg}'s {cw} x {ch} map"))
   out += _vram_problems(regions(plan, assets, later))
   out += _sprite_problems(plan, assets)
   return out


def _vram_problems(found: list[Region]) -> list[Problem]:
   """!Background video memory clashes: a map over tiles or over another map, tiles over other tiles, past 64 KB.
   @param found  regions()
   @return problems
   """
   out = []
   for r in found:
      if r.end > BG_VRAM:
         out.append(Problem("error", f"BG{r.bg}", f"{r.owner} ends at 0x{r.end:X}, past background video memory "
                                                  f"(0x{BG_VRAM:X})"))
   for i, a in enumerate(found):
      for b in found[i + 1:]:
         if a.start >= b.end or b.start >= a.end or (a.kind == b.kind == "tiles" and a.source == b.source and
                                                      a.start == b.start):
            continue
         if a.kind == "tiles" and b.kind == "tiles":
            sev = "warning"
            what = f"{b.owner} overwrite {a.owner}"
         else:
            sev = "error"
            what = f"{b.owner} ({_span(b)}) is written over {a.owner} ({_span(a)})" if b.kind == "map" else \
               f"{b.owner} ({_span(b)}) overwrite {a.owner} ({_span(a)})"
         out.append(Problem(sev, f"BG{b.bg}", what))
   return out


@dataclass
class SheetPlace:
   """!Where a sheet's tiles went in sprite memory."""

   ## Its tag.
   tag: int
   ## First tile, or -1 when it does not fit.
   start: int
   ## Tiles.
   count: int
   ## The tiles' record, or None (reserved).
   record: JsonDict | None


def place_sheets(plan: JsonDict, assets: Assets) -> list[SheetPlace]:
   """!Sheets placed first fit over the 1024 sprite tiles in plan order (sprites::load_sheet() / reserve_sheet()).
   @param plan    plan data
   @param assets  the compiled assets
   @return one per sheet
   """
   used = [False] * OBJ_TILES
   out = []
   for sh in plan.get("sheets", []):
      rec = assets.get(value(sh, "sheets", "tiles"), "tiles")
      count = rec["count"] if rec is not None else value(sh, "sheets", "reserve")
      start = -1
      if count > 0:
         run = 0
         for t in range(OBJ_TILES):
            run = 0 if used[t] else run + 1
            if run == count:
               start = t - count + 1
               break
      if start >= 0:
         for t in range(start, start + count):
            used[t] = True
      out.append(SheetPlace(value(sh, "sheets", "tag"), start, count, rec))
   return out


def obj_banks(plan: JsonDict) -> dict[int, int]:
   """!The OBJ bank each palette tag gets (the first free one, in plan order; a tag loaded again keeps its bank).
   @param plan  plan data
   @return {tag: bank}
   """
   out: dict[int, int] = {}
   for p in plan.get("palettes", []):
      if value(p, "palettes", "target") != "obj":
         continue
      tag = value(p, "palettes", "tag")
      if tag not in out and len(out) < OBJ_BANKS:
         out[tag] = len(out)
   return out


def _sprite_problems(plan: JsonDict, assets: Assets) -> list[Problem]:
   """!Sheets, palettes and sprites that do not fit or name nothing.
   @param plan    plan data
   @param assets  the compiled assets
   @return problems
   """
   out = []
   tags: dict[int, int] = {}
   for i, (sh, place) in enumerate(zip(plan.get("sheets", []), place_sheets(plan, assets))):
      where = f"sheets {i}"
      if place.tag in tags:
         out.append(Problem("error", where, f"tag {place.tag} is sheets {tags[place.tag]}'s too"))
      tags.setdefault(place.tag, i)
      if sh.get("tiles"):
         if place.record is None:
            out.append(Problem("error", where, f"{sh['tiles']}: {assets.errors.get(sh['tiles'])}"))
         elif place.record["bpp"] != sg.BPP4:
            out.append(Problem("error", where, f"{sh['tiles']} is 8bpp; sprite sheets are 4bpp"))
         if value(sh, "sheets", "reserve"):
            out.append(Problem("warning", where, "it loads tiles and reserves some: the reserve is ignored"))
      elif not value(sh, "sheets", "reserve"):
         out.append(Problem("error", where, "neither tiles nor a reserve"))
      if place.count and place.start < 0:
         out.append(Problem("error", where, f"its {place.count} tiles do not fit in sprite memory after the sheets "
                                            f"before it ({OBJ_TILES} tiles)"))
   palettes = plan.get("palettes", [])
   banks = obj_banks(plan)
   for i, p in enumerate(palettes):
      where = f"palettes {i}"
      rec = assets.get(value(p, "palettes", "palette"), "palette")
      if rec is None:
         out.append(Problem("error", where, f"{p.get('palette') or 'no palette'}: "
                                            f"{assets.errors.get(p.get('palette', ''), 'pick a palette asset')}"))
         continue
      have = -(-len(rec["colors"]) // sg.BANK_SIZE) - value(p, "palettes", "from_bank")
      want = 1 if value(p, "palettes", "target") == "obj" else value(p, "palettes", "banks")
      if have < want:
         out.append(Problem("warning", where, f"{p['palette']} has {max(have, 0)} bank(s) from bank "
                                              f"{value(p, 'palettes', 'from_bank')}; {want} are loaded"))
      if value(p, "palettes", "target") == "bg" and value(p, "palettes", "bank") + want > sg.BANKS:
         out.append(Problem("error", where, f"banks {value(p, 'palettes', 'bank')}-"
                                            f"{value(p, 'palettes', 'bank') + want - 1}: BG memory has {sg.BANKS}"))
      if value(p, "palettes", "target") == "obj" and value(p, "palettes", "tag") not in banks:
         out.append(Problem("error", where, f"no OBJ bank is free for tag {p.get('tag')}"))
   sprites = plan.get("sprites", [])
   most = limits()["sprites"]
   if len(sprites) > most:
      out.append(Problem("error", "sprites", f"{len(sprites)} sprites; a screen has {most}"))
   placed = {pl.tag: pl for pl in place_sheets(plan, assets)}
   for i, s in enumerate(sprites):
      where = f"sprites {i}"
      pl = placed.get(value(s, "sprites", "sheet"))
      if pl is None:
         out.append(Problem("error", where, f"no sheet has tag {value(s, 'sprites', 'sheet')}"))
      else:
         w, h = obj_size(value(s, "sprites", "shape"), value(s, "sprites", "size"))
         need = value(s, "sprites", "frame") + (w // TILE) * (h // TILE)
         if need > pl.count:
            out.append(Problem("warning", where, f"its frame shows tiles {value(s, 'sprites', 'frame')}-{need - 1} "
                                                 f"of sheet {pl.tag}, which has {pl.count}"))
      if value(s, "sprites", "palette_tag") not in banks:
         out.append(Problem("error", where, f"no OBJ palette has tag {value(s, 'sprites', 'palette_tag')}"))
   return out


# -- transitions -----------------------------------------------------------------------------------------------------


def fade_frames(fade: JsonDict | None, style: JsonDict) -> list[tuple[int, int]]:
   """!A fade call by call, as screen::fade steps it (begin() makes the first call): after each call, the blend
   amount the BG banks and the OBJ banks of its mask show.
   @param fade   fade_of()'s object, or None (no fade)
   @param style  fade_style()'s
   @return (bg y, obj y) per call; empty for no fade
   """
   if fade is None:
      return []
   y, step, delay = fade["from"], style["step"], fade["delay"]
   if delay < 0:
      step, delay = step - delay, 0
   waited, obj_turn, finishing, finished = delay, False, False, 0
   bg_y = obj_y = fade["from"]
   out: list[tuple[int, int]] = []

   def advance(y_: int) -> tuple[int, bool]:
      """!One step toward the target.
      @param y_  y now
      @return (new y, finishing)
      """
      if y_ == fade["to"]:
         return y_, True
      if y_ < fade["to"]:
         return min(y_ + step, fade["to"]), False
      return max(y_ - step, fade["to"]), False

   while len(out) < MAX_FADE_CALLS:
      if finishing:
         if finished == style["finish_calls"]:
            out.append((bg_y, obj_y))
            break
         finished += 1
         out.append((bg_y, obj_y))
         continue
      if not obj_turn:
         if waited < delay:
            waited += 1
            out.append((bg_y, obj_y))
            continue
         waited = 0
      if not style["alternate"]:
         bg_y = obj_y = y
         y, finishing = advance(y)
      else:
         if obj_turn:
            obj_y = y
         else:
            bg_y = y
         obj_turn = not obj_turn
         if not obj_turn:
            y, finishing = advance(y)
      out.append((bg_y, obj_y))
   return out


def blend(base: int, target: int, coef: int, rounding: str = "floor") -> int:
   """!A BGR555 colour blended toward another as gfx::palette does it (blend_floor(): an arithmetic shift; blend():
   toward zero).
   @param base      the colour
   @param target    the colour blended toward
   @param coef      0 (base) to 16 (target)
   @param rounding  floor or truncate
   @return the colour
   """
   out = 0
   for shift in (0, GREEN_SHIFT, BLUE_SHIFT):
      b, t = base >> shift & CHANNEL_MASK, target >> shift & CHANNEL_MASK
      d = (t - b) * coef
      step = d // FULL if rounding == "floor" or d >= 0 else -((-d) // FULL)
      out |= (b + step) << shift
   return out


# -- the picture -----------------------------------------------------------------------------------------------------


@dataclass
class Fade:
   """!A fade level the preview shows: BG and OBJ blend amounts toward a colour over a bank mask."""

   ## BG banks' amount (0-16).
   bg_y: int
   ## OBJ banks' amount.
   obj_y: int
   ## The fade colour (BGR555).
   color: int
   ## The bank mask.
   mask: int
   ## floor or truncate.
   rounding: str = "floor"


def fade_at(plan: JsonDict, which: str, call: int) -> Fade | None:
   """!A transition's state after one of its calls (the last call when past it).
   @param plan   plan data
   @param which  open, in or out
   @param call   0-based call
   @return the Fade, or None (no fade)
   """
   f = fade_of(transition(plan, which))
   frames = fade_frames(f, fade_style(plan))
   if f is None or not frames:
      return None
   bg_y, obj_y = frames[min(call, len(frames) - 1)]
   return Fade(bg_y, obj_y, sg.to_bgr555(f["color"]), f["mask"], fade_style(plan)["rounding"])


def palettes_of(plan: JsonDict, assets: Assets) -> tuple[list[int], list[int]]:
   """!BG and OBJ palette memory after the plan's loads.
   @param plan    plan data
   @param assets  the compiled assets
   @return (256 BG colours, 256 OBJ colours)
   """
   bg, obj = [0] * sg.PALETTE_ENTRIES, [0] * sg.PALETTE_ENTRIES
   banks = obj_banks(plan)
   for p in plan.get("palettes", []):
      rec = assets.get(value(p, "palettes", "palette"), "palette")
      if rec is None:
         continue
      src = rec["colors"][value(p, "palettes", "from_bank") * sg.BANK_SIZE:]
      if value(p, "palettes", "target") == "obj":
         tag = value(p, "palettes", "tag")
         if tag not in banks:
            continue
         first, n = banks[tag] * sg.BANK_SIZE, sg.BANK_SIZE
         dest = obj
      else:
         first, n = value(p, "palettes", "bank") * sg.BANK_SIZE, value(p, "palettes", "banks") * sg.BANK_SIZE
         dest = bg
      for i, c in enumerate(src[:n]):
         if first + i < len(dest):
            dest[first + i] = c
   return bg, obj


def _faded(colors: list[int], fade: Fade | None, obj: bool) -> list[int]:
   """!Palette memory with a fade applied to the banks of its mask.
   @param colors  256 colours
   @param fade    the Fade, or None
   @param obj     OBJ memory (the mask's upper half)
   @return the colours
   """
   if fade is None:
      return colors
   y = fade.obj_y if obj else fade.bg_y
   out = list(colors)
   for bank in range(sg.BANKS):
      bit = bank + (BG_MASK_BITS if obj else 0)
      if fade.mask >> bit & 1:
         for i in range(bank * sg.BANK_SIZE, (bank + 1) * sg.BANK_SIZE):
            out[i] = blend(colors[i], fade.color, y, fade.rounding)
   return out


def bg_vram(plan: JsonDict, assets: Assets, later: bool = False) -> bytearray:
   """!Background video memory after the plan's writes: each layer's tiles, its windows cleared to their fill index,
   its tilemap, then its windows' cells (layers::put_window()), in layer order. Writes past 64 KB are dropped.
   @param plan    plan data
   @param assets  the compiled assets
   @param later   with the later templates applied
   @return 64 KB
   """
   vram = bytearray(BG_VRAM)
   mode = plan.get("mode", 0)

   def write(at: int, data: bytes) -> None:
      """!Writes bytes, dropping what falls past the end.
      @param at    first byte
      @param data  the bytes
      @return None
      """
      if 0 <= at < BG_VRAM:
         part = data[:BG_VRAM - at]
         vram[at:at + len(part)] = part

   layers = sorted(active_layers(plan, later).items())
   for bg, lay in layers:
      tb = tile_bytes_of(lay, mode)
      cb = value(lay, "layers", "char_block") * CHAR_BLOCK_BYTES
      rec = assets.get(value(lay, "layers", "tiles"), "tiles")
      if rec is not None:
         start = cb + (value(lay, "layers", "first_tile") + value(lay, "layers", "tiles_offset")) * tb
         write(start, b"".join(w.to_bytes(sg.WORD_BYTES, "little") for w in rec["words"]))
      for w in plan.get("windows", []):
         if value(w, "windows", "bg") == bg:
            fill = value(w, "windows", "fill")
            byte = fill if tb == sg.TILE_BYTES_8BPP else fill | fill << sg.NIBBLE_BITS
            n = value(w, "windows", "w") * value(w, "windows", "h")
            write(cb + value(w, "windows", "first_tile") * tb, bytes([byte]) * (n * tb))
   for bg, lay in layers:
      affine = is_affine(mode, bg)
      sb = value(lay, "layers", "screen_block") * SCREEN_BLOCK_BYTES
      limit = map_bytes(lay, mode)
      mp = assets.get(value(lay, "layers", "tilemap"), "tilemap")
      if mp is not None:
         off = value(lay, "layers", "tilemap_offset")
         if affine:
            data = bytes(c & sg.BYTE_MASK for c in mp["cells"])[:max(0, limit - off)]
            write(sb + off, data)
         else:
            room = max(0, limit // sg.ENTRY_BYTES - off)
            write(sb + off * sg.ENTRY_BYTES, b"".join(c.to_bytes(sg.ENTRY_BYTES, "little") for c in mp["cells"][:room]))
      for w in plan.get("windows", []):
         if value(w, "windows", "bg") != bg:
            continue
         tile, bank = value(w, "windows", "first_tile"), value(w, "windows", "palette")
         for y in range(value(w, "windows", "y"), value(w, "windows", "y") + value(w, "windows", "h")):
            for x in range(value(w, "windows", "x"), value(w, "windows", "x") + value(w, "windows", "w")):
               i = cell_index(lay, mode, x, y)
               if affine:
                  write(sb + i, bytes([tile & sg.BYTE_MASK]))
               else:
                  write(sb + i * sg.ENTRY_BYTES, sg.make_entry(tile & MAX_TILE, bank).to_bytes(sg.ENTRY_BYTES,
                                                                                                "little"))
               tile += 1
   return vram


## A layer's picture: palette memory index per screen pixel (-1 transparent).
IndexLayer = list[int]


def _layer_pixels(vram: bytes, lay: JsonDict, mode: int) -> IndexLayer:
   """!One layer on screen: the BG palette index of each pixel (-1 transparent), its scroll applied.
   @param vram  background video memory
   @param lay   layer item
   @param mode  display mode
   @return WIDTH * HEIGHT indices
   """
   out = [-1] * (WIDTH * HEIGHT)
   bg = value(lay, "layers", "bg")
   affine = is_affine(mode, bg)
   tb = tile_bytes_of(lay, mode)
   eight = tb == sg.TILE_BYTES_8BPP
   cb = value(lay, "layers", "char_block") * CHAR_BLOCK_BYTES
   sb = value(lay, "layers", "screen_block") * SCREEN_BLOCK_BYTES
   mw, mh = map_cells(lay, mode)
   sx, sy = (0, 0) if affine else (value(lay, "layers", "scroll_x"), value(lay, "layers", "scroll_y"))
   cache: dict[int, list[list[int]]] = {}
   cells_x = WIDTH // TILE + 1
   cells_y = HEIGHT // TILE + 1
   for cy in range(cells_y):
      for cx in range(cells_x):
         mx, my = (sx // TILE + cx), (sy // TILE + cy)
         if affine and not (0 <= mx < mw and 0 <= my < mh):
            continue
         i = cell_index(lay, mode, mx, my)
         if affine:
            entry = vram[sb + i] if sb + i < BG_VRAM else 0
            tile, bank, hf, vf = entry, 0, False, False
         else:
            at = sb + i * sg.ENTRY_BYTES
            entry = int.from_bytes(vram[at:at + sg.ENTRY_BYTES], "little") if at + 1 < BG_VRAM else 0
            tile, bank, hf, vf = sg.entry_parts(entry)
         rows = cache.get(tile)
         if rows is None:
            at = cb + tile * tb
            raw = bytes(vram[at:at + tb]) if at + tb <= BG_VRAM else bytes(tb)
            rows = sg.tiles_from_bytes(raw, sg.BPP8 if eight else sg.BPP4)[0]
            cache[tile] = rows
         base = 0 if eight else bank * sg.BANK_SIZE
         ox, oy = cx * TILE - sx % TILE, cy * TILE - sy % TILE
         for y in range(TILE):
            py = oy + y
            if not 0 <= py < HEIGHT:
               continue
            row = rows[TILE - 1 - y if vf else y]
            for x in range(TILE):
               px = ox + x
               if 0 <= px < WIDTH:
                  v = row[TILE - 1 - x if hf else x]
                  if v:
                     out[py * WIDTH + px] = base + v
   return out


def _sprite_layers(plan: JsonDict, assets: Assets) -> list[IndexLayer]:
   """!The sprites on screen by priority: the OBJ palette index of each pixel (-1 transparent), the front sprite of
   each pixel kept (OAM order: sorted by priority, subpriority, then the lower one on screen first, as build_oam()).
   @param plan    plan data
   @param assets  the compiled assets
   @return one IndexLayer per priority
   """
   out = [[-1] * (WIDTH * HEIGHT) for _ in range(PRIORITIES)]
   obj = bytearray(OBJ_TILES * sg.TILE_BYTES_4BPP)
   placed = {}
   for pl in place_sheets(plan, assets):
      if pl.start >= 0:
         placed.setdefault(pl.tag, pl)
         if pl.record is not None and pl.record["bpp"] == sg.BPP4:
            at = pl.start * sg.TILE_BYTES_4BPP
            data = b"".join(w.to_bytes(sg.WORD_BYTES, "little") for w in pl.record["words"])
            obj[at:at + len(data)] = data[:len(obj) - at]
   banks = obj_banks(plan)
   order = []
   for n, s in enumerate(plan.get("sprites", [])):
      w, h = obj_size(value(s, "sprites", "shape"), value(s, "sprites", "size"))
      dbl = DOUBLE_BOX if value(s, "sprites", "affine") == "double" else 1
      corner_y = value(s, "sprites", "y") - h * dbl // HALF
      sort_y = corner_y % OAM_Y_WRAP
      if sort_y >= HEIGHT:
         sort_y -= OAM_Y_WRAP
      key = value(s, "sprites", "priority") << BITS_PER_PRIORITY_KEY | value(s, "sprites", "subpriority")
      order.append((key, -sort_y, n, s))
   order.sort(key=lambda entry: entry[:-1])   # key, then the lower sprite first, then creation order
   for _key, _y, _n, s in reversed(order):   # the back sprite first: the front one is written last
      pl = placed.get(value(s, "sprites", "sheet"))
      if pl is None or value(s, "sprites", "mode") == "window":
         continue
      w, h = obj_size(value(s, "sprites", "shape"), value(s, "sprites", "size"))
      # an affine sprite shows with the identity matrix: a double-size one's box is twice as big, its pixels centred
      left, top = value(s, "sprites", "x") - w // HALF, value(s, "sprites", "y") - h // HALF
      first = pl.start + value(s, "sprites", "frame")
      bank = banks.get(value(s, "sprites", "palette_tag"), 0) * sg.BANK_SIZE
      flip = value(s, "sprites", "affine") == "off"
      hf, vf = flip and value(s, "sprites", "hflip"), flip and value(s, "sprites", "vflip")
      layer = out[value(s, "sprites", "priority")]
      tiles_w = w // TILE
      for ty in range(h // TILE):
         for tx in range(tiles_w):
            t = first + ty * tiles_w + tx   # sprite tiles mapped one after the other (1D)
            if not 0 <= t < OBJ_TILES:
               continue
            rows = sg.tiles_from_bytes(bytes(obj[t * sg.TILE_BYTES_4BPP:(t + 1) * sg.TILE_BYTES_4BPP]), sg.BPP4)[0]
            dx = (tiles_w - 1 - tx) * TILE if hf else tx * TILE
            dy = (h // TILE - 1 - ty) * TILE if vf else ty * TILE
            for y in range(TILE):
               py = top + dy + y
               if not 0 <= py < HEIGHT:
                  continue
               row = rows[TILE - 1 - y if vf else y]
               for x in range(TILE):
                  px = left + dx + x
                  v = row[TILE - 1 - x if hf else x]
                  if v and 0 <= px < WIDTH:
                     layer[py * WIDTH + px] = bank + v
   return out



def render(plan: JsonDict, manifest: Document, later: bool = False, fade: Fade | None = None,
           guides: bool = False) -> RgbaImage:
   """!The screen as the GBA shows it after the plan's setup: layers shown in mode order, sprites over layers of
   their priority, the backdrop (BG colour 0) behind; optionally at a fade level and with guides (window outlines,
   sprite boxes).
   @param plan      plan data
   @param manifest  its asset manifest Document
   @param later     with the later templates applied
   @param fade      a fade level, or None
   @param guides    draw window outlines and sprite boxes
   @return (240, 160, RGBA)
   """
   assets = Assets(manifest)
   mode = plan.get("mode", 0)
   vram = bg_vram(plan, assets, later)
   bg_colors, obj_colors = palettes_of(plan, assets)
   bg_colors, obj_colors = _faded(bg_colors, fade, False), _faded(obj_colors, fade, True)
   shown = [(value(lay, "layers", "priority"), bg, _layer_pixels(vram, lay, mode))
            for bg, lay in sorted(active_layers(plan, later).items())
            if bg in LAYERS_OF[mode] and value(lay, "layers", "shown")]
   shown.sort(key=lambda t: (t[0], t[1]))
   sprites = _sprite_layers(plan, assets)
   bg_rgba = [bytes(bgr_to_rgb(c) + (OPAQUE,)) for c in bg_colors]
   obj_rgba = [bytes(bgr_to_rgb(c) + (OPAQUE,)) for c in obj_colors]
   px = bytearray()
   for i in range(WIDTH * HEIGHT):
      color = bg_rgba[0]
      for p in range(PRIORITIES):
         if sprites[p][i] >= 0:
            color = obj_rgba[sprites[p][i]]
            break
         hit = next((pix[i] for prio, _bg, pix in shown if prio == p and pix[i] >= 0), -1)
         if hit >= 0:
            color = bg_rgba[hit]
            break
      px += color
   img = (WIDTH, HEIGHT, px)
   if guides:
      _draw_guides(img, plan, later)
   return img


def _outline(img: RgbaImage, x: int, y: int, w: int, h: int) -> None:
   """!A one-pixel rectangle outline in GUIDE_COLOR.
   @param img  target
   @param x    left
   @param y    top
   @param w    width
   @param h    height
   @return None
   """
   iw, ih, px = img
   color = bytes(GUIDE_COLOR)
   for xx in range(x, x + w):
      for yy in (y, y + h - 1):
         if 0 <= xx < iw and 0 <= yy < ih:
            px[(yy * iw + xx) * RGBA_BYTES:(yy * iw + xx + 1) * RGBA_BYTES] = color
   for yy in range(y, y + h):
      for xx in (x, x + w - 1):
         if 0 <= xx < iw and 0 <= yy < ih:
            px[(yy * iw + xx) * RGBA_BYTES:(yy * iw + xx + 1) * RGBA_BYTES] = color


def _draw_guides(img: RgbaImage, plan: JsonDict, later: bool) -> None:
   """!Window outlines (their layer's scroll applied) and sprite boxes.
   @param img    target
   @param plan   plan data
   @param later  with the later templates applied
   @return None
   """
   layers = active_layers(plan, later)
   for w in plan.get("windows", []):
      lay = layers.get(value(w, "windows", "bg"))
      sx, sy = (value(lay, "layers", "scroll_x"), value(lay, "layers", "scroll_y")) if lay else (0, 0)
      _outline(img, value(w, "windows", "x") * TILE - sx, value(w, "windows", "y") * TILE - sy,
               value(w, "windows", "w") * TILE, value(w, "windows", "h") * TILE)
   for s in plan.get("sprites", []):
      w, h = obj_size(value(s, "sprites", "shape"), value(s, "sprites", "size"))
      dbl = DOUBLE_BOX if value(s, "sprites", "affine") == "double" else 1
      _outline(img, value(s, "sprites", "x") - w * dbl // HALF, value(s, "sprites", "y") - h * dbl // HALF,
               w * dbl, h * dbl)


def vram_lines(plan: JsonDict, manifest: Document, later: bool = False) -> list[str]:
   """!Background video memory as the plan uses it (the panel's and the command line's memory view).
   @param plan      plan data
   @param manifest  its asset manifest Document
   @param later     with the later templates applied
   @return lines, by address
   """
   assets = Assets(manifest)
   out = []
   for r in sorted(regions(plan, assets, later), key=lambda r: (r.start, r.end)):
      blocks = f"char block {r.start // CHAR_BLOCK_BYTES}" if r.kind == "tiles" else \
         f"screen blocks {r.start // SCREEN_BLOCK_BYTES}-{(r.end - 1) // SCREEN_BLOCK_BYTES}"
      out.append(f"{_span(r)}  {r.end - r.start:6d} B  {blocks:20s} {r.owner}")
   for pl in place_sheets(plan, assets):
      if pl.start >= 0:
         what = "reserved" if pl.record is None else "loaded"
         out.append(f"OBJ tiles {pl.start}-{pl.start + pl.count - 1}  sheet tag {pl.tag} ({what})")
   for tag, bank in obj_banks(plan).items():
      out.append(f"OBJ bank {bank}  palette tag {tag}")
   return out


# -- export ----------------------------------------------------------------------------------------------------------


def camel(name: str) -> str:
   """!A snake_case name in CamelCase (the export's constant names).
   @param name  snake_case
   @return CamelCase
   """
   return "".join(part[:1].upper() + part[1:] for part in name.split("_") if part)


def _cpp_transition(plan: JsonDict, which: str) -> str:
   """!A transition as a C++ initializer.
   @param plan   plan data
   @param which  open, in or out
   @return the expression
   """
   raw = transition(plan, which)
   style = fade_style(plan)
   presets = engine_lists()["presets"]
   custom_style = style != handheld()
   if isinstance(raw, str) and raw in presets and not custom_style:
      return "screen::" + presets[raw]
   f = fade_of(raw)
   if f is None:
      return "screen::" + presets["none"]
   return (f"{{.on = true, .fade = {{.mask = 0x{f['mask']:08X}u, .delay = {f['delay']}, .from = {f['from']}, "
           f".to = {f['to']}, .color = 0x{sg.to_bgr555(f['color']):04X}}}, .style = kFadeStyle}}")


def export_cpp(plan: JsonDict, source: str = "") -> str:
   """!The plan as a C++ header: the layer templates and Plan, the frame steps, the transitions, the windows' and
   sprites' places and the sheet / palette tags, in a namespace of the plan's name. Every number sits in a constexpr
   definition, named by its field (designated initializers), as the project's style asks.
   @param plan    plan data
   @param source  the plan file's name, for the header comment
   @return the header text
   """
   problems = [p for p in check(plan, None) if p.severity == "error"]
   if problems:
      raise PlanError("the plan has errors: " + "; ".join(str(p) for p in problems))
   name = plan["name"]
   cc = camel(name)
   mode = plan.get("mode", 0)
   lines = [f"/// @file",
            f"/// Screen plan {name!r} (generated by capsule-studio from {source or name + SUFFIX}; edit the plan in",
            "/// the studio and export it again rather than editing this file).",
            "#pragma once", "",
            '#include "capsule/hal/video.h"', '#include "capsule/screen/screen.h"',
            '#include "capsule/screen/sprites.h"', '#include "capsule/text/window.h"',
            "", "#include <cstdint>", "",
            f"/// The {name} screen's plan.", f"namespace {name}_screen", "{", "",
            "namespace screen = capsule::screen;", "namespace layers = capsule::screen::layers;",
            "namespace video = capsule::hal::video;", ""]

   def template(lay: JsonDict) -> str:
      """!One layer template's initializer.
      @param lay  layer item
      @return text
      """
      bpp8 = 1 if value(lay, "layers", "bpp8") or is_affine(mode, value(lay, "layers", "bg")) else 0
      return (f"{{.bg = {value(lay, 'layers', 'bg')}, .char_block = {value(lay, 'layers', 'char_block')}, "
              f".screen_block = {value(lay, 'layers', 'screen_block')}, "
              f".screen_size = {value(lay, 'layers', 'screen_size')}, .bpp8 = {bpp8}, "
              f".priority = {value(lay, 'layers', 'priority')}, .first_tile = {value(lay, 'layers', 'first_tile')}}}")

   plan_layers = [lay for lay in plan.get("layers", []) if not value(lay, "layers", "later")]
   later_layers = [lay for lay in plan.get("layers", []) if value(lay, "layers", "later")]
   lines.append(f"/// The display mode.")
   lines.append(f"inline constexpr uint8_t kMode = {mode};")
   if plan_layers:
      lines.append("/// The plan's layers (layers::LayerTemplate).")
      lines.append("inline constexpr layers::LayerTemplate kLayers[] = {")
      lines += [f"   {template(lay)}," for lay in plan_layers]
      lines.append("};")
      lines.append("/// The layer plan the screen applies before its setup.")
      lines.append("inline constexpr layers::Plan kPlan = {.layers = kLayers, "
                   ".count = static_cast<uint8_t>(sizeof(kLayers) / sizeof(kLayers[0])), .mode = kMode};")
   else:
      lines.append("/// The layer plan the screen applies before its setup (no layers).")
      lines.append("inline constexpr layers::Plan kPlan = {.layers = nullptr, .count = 0, .mode = kMode};")
   for lay in later_layers:
      bg = value(lay, "layers", "bg")
      lines.append(f"/// A template the screen applies later with layers::init() (BG{bg}).")
      lines.append(f"inline constexpr layers::LayerTemplate kLaterBg{bg} = {template(lay)};")
   lines.append("")
   steps = plan.get("steps", default_steps())
   names = engine_lists()["steps"]
   lines.append("/// The screen's frame order (Screen::steps).")
   lines.append("inline constexpr screen::Step kSteps[] = {" +
                ", ".join(f"screen::Step::{names[s]}" for s in steps) + "};" if steps else
                "inline constexpr const screen::Step* kSteps = nullptr;")
   lines.append("/// Entries of kSteps (Screen::step_count).")
   lines.append("inline constexpr uint8_t kStepCount = " +
                ("static_cast<uint8_t>(sizeof(kSteps) / sizeof(kSteps[0]));" if steps else "0;"))
   style = fade_style(plan)
   if style != handheld():
      lines.append("/// The plan's fade style.")
      lines.append(f"inline constexpr screen::fade::FadeStyle kFadeStyle = {{.step = {style['step']}, "
                   f".finish_calls = {style['finish_calls']}, .alternate = {str(style['alternate']).lower()}, "
                   f".rounding = capsule::gfx::palette::Rounding::{engine_lists()['roundings'][style['rounding']]}}};")
   else:
      lines.append("/// The plan's fade style (the engine's).")
      lines.append("inline constexpr screen::fade::FadeStyle kFadeStyle = screen::fade::kHandheldFade;")
   for which in TRANSITIONS:
      lines.append(f"/// Screen::{which}.")
      lines.append(f"inline constexpr screen::Transition k{camel(which)} = {_cpp_transition(plan, which)};")
   lines.append("")
   windows = plan.get("windows", [])
   if windows:
      lines += ["/// A window's place: its layer, cells, first tile and bank (layers::put_window()'s arguments).",
                "struct WindowPlace", "{", "   video::BgIndex bg;     ///< Its layer.",
                "   uint8_t x;             ///< Left column.", "   uint8_t y;             ///< Top row.",
                "   uint8_t w;             ///< Columns.", "   uint8_t h;             ///< Rows.",
                "   uint16_t first_tile;   ///< Its first tile in the layer's character block.",
                "   uint8_t palette;       ///< Its bank.", "};"]
      for w in windows:
         lines.append(f"/// The {value(w, 'windows', 'name')} window.")
         lines.append(f"inline constexpr WindowPlace k{camel(value(w, 'windows', 'name'))}Window = "
                      f"{{.bg = {value(w, 'windows', 'bg')}, .x = {value(w, 'windows', 'x')}, "
                      f".y = {value(w, 'windows', 'y')}, .w = {value(w, 'windows', 'w')}, "
                      f".h = {value(w, 'windows', 'h')}, .first_tile = {value(w, 'windows', 'first_tile')}, "
                      f".palette = {value(w, 'windows', 'palette')}}};")
         st = window_storage(w)   # the screen gives the window its tiles (window::attach())
         lines.append(f"/// The {value(w, 'windows', 'name')} window's tiles ({st.tiles} tiles, {st.size_bytes} bytes; "
                      "a member of the screen's arena block).")
         place = f"k{camel(value(w, 'windows', 'name'))}Window"
         lines.append(f"using {camel(value(w, 'windows', 'name'))}WindowTiles = "
                      f"capsule::text::window::TileBuffer<{place}.w, {place}.h>;")
      tiles, size = windows_storage(plan)
      lines.append("/// Tiles of all the plan's window buffers.")
      lines.append(f"inline constexpr int kWindowTiles = {tiles};")
      lines.append(f"/// Bytes of them ({size}: kWordsPerTile words of 4 bytes a tile).")
      lines.append("inline constexpr int kWindowBytes = kWindowTiles * capsule::text::window::kBytesPerTile;")
      lines.append("")
   for sh in plan.get("sheets", []):
      what = sh.get("tiles") or f"{value(sh, 'sheets', 'reserve')} reserved tiles"
      lines.append(f"/// Tile tag of the sheet {what}.")
      lines.append(f"inline constexpr uint16_t kSheet{value(sh, 'sheets', 'tag')}Tag = {value(sh, 'sheets', 'tag')};")
      if not sh.get("tiles"):
         lines.append(f"/// Tiles sprites::reserve_sheet() takes for tag {value(sh, 'sheets', 'tag')}.")
         lines.append(f"inline constexpr uint16_t kSheet{value(sh, 'sheets', 'tag')}Reserve = "
                      f"{value(sh, 'sheets', 'reserve')};")
   emitted: set[str] = set()
   for p in plan.get("palettes", []):
      if value(p, "palettes", "target") == "obj":
         const = f"kPalette{value(p, 'palettes', 'tag')}Tag"
         text = [f"/// OBJ palette tag of {p.get('palette')}.",
                 f"inline constexpr uint16_t {const} = {value(p, 'palettes', 'tag')};"]
      else:
         const = f"k{camel(str(p.get('palette', '')).split(':', 1)[-1].lower())}Bank{value(p, 'palettes', 'bank')}"
         text = [f"/// A BG bank palette {p.get('palette')} loads at.",
                 f"inline constexpr uint8_t {const} = {value(p, 'palettes', 'bank')};"]
      if const not in emitted:   # the same palette tag or bank twice: one constant
         emitted.add(const)
         lines += text
   sprites = plan.get("sprites", [])
   if sprites:
      lines += ["", "/// A sprite's place: what sprites::create() and its template take from the plan.",
                "struct SpritePlace", "{", "   int16_t x;                ///< Centre x.",
                "   int16_t y;                ///< Centre y.", "   uint8_t subpriority;      ///< Lower in front.",
                "   uint8_t priority;         ///< 0 (front) to 3.", "   uint16_t sheet_tag;       ///< Its sheet.",
                "   uint16_t palette_tag;     ///< Its palette.", "   video::ObjShape shape;    ///< OBJ shape.",
                "   uint8_t size;             ///< OBJ size 0-3.",
                "   int16_t frame;            ///< Tile shown, from the sheet's first.", "};"]
      for s in sprites:
         lines.append(f"/// The {value(s, 'sprites', 'name')} sprite.")
         lines.append(f"inline constexpr SpritePlace k{camel(value(s, 'sprites', 'name'))}Sprite = "
                      f"{{.x = {value(s, 'sprites', 'x')}, .y = {value(s, 'sprites', 'y')}, "
                      f".subpriority = {value(s, 'sprites', 'subpriority')}, "
                      f".priority = {value(s, 'sprites', 'priority')}, .sheet_tag = {value(s, 'sprites', 'sheet')}, "
                      f".palette_tag = {value(s, 'sprites', 'palette_tag')}, "
                      f".shape = video::{engine_lists()['shapes'][value(s, 'sprites', 'shape')]}, "
                      f".size = {value(s, 'sprites', 'size')}, .frame = {value(s, 'sprites', 'frame')}}};")
   lines += _cpp_exit(plan)
   lines += ["", f"}}   // namespace {name}_screen", ""]
   return "\n".join(_wrap(line) for line in lines)


def _cpp_exit(plan: JsonDict) -> list[str]:
   """!The export's leave() helper, the plan's exit as the screen calls it.
   @param plan  plan data
   @return lines
   """
   ex = exit_of(plan)
   call = ex["call"]
   frames = exit_frames(plan)
   last = frames[-1][0]
   what = "its out fade, then it leaves" if call not in UNFADED else "no out fade: it leaves at the frame's end"
   out = ["", f"/// How the screen leaves: screen::{call}() ({what}; what comes next starts {last} frame(s) after "
              "the call)."]
   if call in REPLACING:
      nxt = ex["next"] or "the next"
      out += [f"/// @param next  the screen that takes its place ({nxt} screen)", "/// @param arg   its argument",
              "inline void leave(const screen::Screen& next, uint8_t arg)", "{", f"   screen::{call}(next, arg);", "}"]
   else:
      out += ["inline void leave()", "{", f"   screen::{call}();", "}"]
   return out


## Longest exported line before it is wrapped at its initializer's commas.
CPP_LINE = 120
## Indent of a wrapped initializer's continuation lines.
CPP_CONTINUATION = "   "


def _wrap(line: str) -> str:
   """!Wraps a long exported line at the commas of its initializer.
   @param line  one line
   @return the line, or several
   """
   if len(line) <= CPP_LINE or "{" not in line:
      return line
   head, _sep, rest = line.partition("{")
   out, current = [], head + "{"
   for part in rest.split(", "):
      piece = part if current.endswith("{") else ", " + part
      if len(current) + len(piece) > CPP_LINE:
         out.append(current + ",")
         current = CPP_CONTINUATION + part
      else:
         current += piece
   out.append(current)
   return "\n".join(out)


def describe(plan: JsonDict) -> list[str]:
   """!The plan as text (the command line's show).
   @param plan  plan data
   @return lines
   """
   out = [f"plan {plan.get('name')}: mode {plan.get('mode', 0)}, assets {plan.get('assets')}"]
   for section in SECTIONS:
      for i, item in enumerate(plan.get(section, [])):
         fields = ", ".join(f"{f.key}={value(item, section, f.key)}" for f in FIELDS[section]
                            if value(item, section, f.key) != f.default or f.key in ("bg", "tag", "name"))
         out.append(f"{section} {i}: {fields}")
   out.append("steps: " + ", ".join(plan.get("steps", default_steps())))
   for which in TRANSITIONS:
      t = transition(plan, which)
      out.append(f"transition {which}: {t if isinstance(t, str) else json.dumps(t)}")
   for i, w in enumerate(plan.get("windows", [])):   # the text windows and interactions
      out.append(f"window {i} {value(w, 'windows', 'name')} storage: {window_storage(w).text()}")
   tiles, size = windows_storage(plan)
   out.append(f"window buffers: {tiles} tiles, {size} bytes")
   ex = exit_of(plan)
   out.append(f"exit: {ex['call']}" + (f" -> {ex['next'] or '(no next screen)'}" if ex["call"] in REPLACING else ""))
   try:
      out += [f"  frame {f}: {what}" for f, what in exit_frames(plan)]
   except PlanError as e:
      out.append(f"  {e}")
   return out
