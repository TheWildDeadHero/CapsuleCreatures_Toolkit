"""!Sprite animation editing: frames, frame durations, image import.

A sprite asset has frames (images or shape lists, all the sprite's size) and
animations. An animation is a list of steps, each showing one frame for a
duration in display frames (1-255; the GBA shows about 59.73 per second).
Several steps may show the same frame, so holds and ping-pongs cost no tiles.

I3: an animation's steps may be drawn mirrored ("flips": one value per
step, 0 none, 1 horizontal, 2 vertical, 3 both; the steps keep them when
they are duplicated, moved or removed), a sprite may be streamed ("stream":
only the shown frame is in VRAM, so frames x tiles may exceed a slot) and
have a step table ("steps": the walk animations' standing and starting
entries), and a frame may be frame n of an indexed sheet ({"image",
"frame", "indexed": true}: a palette PNG's indices used as they are).

Functions here change a Document and must be called inside doc.edit(),
except the read-only ones (steps(), sizes, budget, playback).
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from . import engine, imaging
from .imaging import HALF, IMAGE_SIZE_FIELDS
from .mapview import PALETTE_COLORS, TILE
from .preview import BLUE_SHIFT, CHANNEL_MASK, GREEN_SHIFT

if TYPE_CHECKING:
   from .document import Document
   from .imaging import RgbaImage
   from .manifest_io import JsonDict
   from .preview import Color5

## One animation step: [frame index, duration in display frames] (internally [frame, duration, flips], I3).
Step = list[int]
## A step's mirroring when it has none (I3: asset::kFlipH 1, kFlipV 2).
NO_FLIP = 0
## Position of a step's flips in an internal step.
FLIP_FIELD = 2

## GBA clock, cycles per second (display rate = GBA_CLOCK / GBA_FRAME_CYCLES, about 59.73).
GBA_CLOCK = 16777216
## GBA cycles per display frame.
GBA_FRAME_CYCLES = 280896
## Duration given to new steps, display frames.
DEFAULT_DURATION = 8
## Step duration of an animation stored without "period" or "durations" (the compiler's default), display frames.
DEFAULT_PERIOD = 8
## Milliseconds per second.
MS_PER_SECOND = 1000
## Largest OBJ size, (width, height).
LARGEST_SIZE = (64, 64)
## 32-bit words of tile data per tile (one per row of 8 pixels).
WORDS_PER_TILE = 8
## Bits per pixel of 4bpp tile data.
BITS_PER_PIXEL = 4
## Mask of one 4bpp pixel's palette index.
PIXEL_MASK = 0xF
## Longest step, display frames.
MAX_DURATION = 255
## Most steps in one animation.
MAX_STEPS = 255
## OBJ sizes as (width, height), smallest area first.
SPRITE_SIZES = sorted([(8, 8), (16, 16), (32, 32), (64, 64), (16, 8), (32, 8), (32, 16), (64, 32),
                       (8, 16), (8, 32), (16, 32), (32, 64)], key=lambda s: (s[0] * s[1], s))


def frames_to_ms(frames: int) -> int:
   """!A duration in milliseconds on the GBA.
   @param frames  display frames
   @return milliseconds, rounded
   """
   # Whole-number math: frames * cycles per frame / cycles per second, rounded to the nearest millisecond.
   return (frames * MS_PER_SECOND * GBA_FRAME_CYCLES + GBA_CLOCK // HALF) // GBA_CLOCK


def smallest_size(w: int, h: int) -> tuple[int, int]:
   """!The smallest OBJ size an image fits in.
   @param w  image width
   @param h  image height
   @return (width, height), or (64, 64) when nothing is large enough
   """
   for size in SPRITE_SIZES:
      if size[0] >= w and size[1] >= h:
         return size
   return LARGEST_SIZE


def tiles_per_frame(asset: JsonDict) -> int:
   """!8x8 tiles one frame uses.
   @param asset  sprite asset
   @return tile count
   """
   return (asset.get("width", TILE) // TILE) * (asset.get("height", TILE) // TILE)


def tile_budget(asset: JsonDict) -> tuple[int, int]:
   """!Tiles the sprite uses against what a sprite slot holds (I3: a streamed sprite keeps one frame there).
   @param asset  sprite asset
   @return (used, limit)
   """
   frames = 1 if asset.get("stream") is True else len(asset.get("frames", []))
   return tiles_per_frame(asset) * frames, engine.sprite_tiles_per_slot()


def new_sprite(doc: Document, key: str, w: int, h: int, index: int | None = None) -> JsonDict:
   """!Adds an empty sprite with an auto palette and one empty animation.
   It compiles once it has a frame.
   @param doc    Document
   @param key    e.g. "sprite:HERO WALK"
   @param w      width (an OBJ size)
   @param h      height
   @param index  position in the manifest, or None for the end
   @return the asset
   """
   if (w, h) not in SPRITE_SIZES:
      raise ValueError(f"{w}x{h} is not a sprite size")
   return doc.add_asset({"key": key, "kind": "sprite", "width": w, "height": h, "palette": "auto",
                         "frames": [], "animations": [{"frames": [], "durations": []}]}, index)


def animation(asset: JsonDict, n: int) -> JsonDict:
   """!One animation, created when the sprite has none yet.
   @param asset  sprite asset
   @param n      animation index
   @return the animation object
   """
   anims = asset.setdefault("animations", [{"frames": [], "durations": []}])
   if not anims:
      anims.append({"frames": [], "durations": []})
   return anims[n]


def steps(asset: JsonDict, n: int = 0) -> list[Step]:
   """!The steps of an animation, whatever form it is stored in.
   @param asset  sprite asset
   @param n      animation index
   @return list of [frame, duration]
   """
   anims = asset.get("animations") or [{"frames": [0], "period": 1}]   # the compiler's default
   a = anims[n]
   fr = a.get("frames", [])
   if isinstance(a.get("durations"), list):
      return [[f, d] for f, d in zip(fr, a["durations"])]
   return [[f, a.get("period", DEFAULT_PERIOD)] for f in fr]


def _steps3(asset: JsonDict, n: int = 0) -> list[Step]:
   """!The steps of an animation with their flips (I3): [frame, duration, flips].
   @param asset  sprite asset
   @param n      animation index
   @return list of [frame, duration, flips]
   """
   st = steps(asset, n)
   anims = asset.get("animations") or [{}]
   flips = anims[n].get("flips") if n < len(anims) else None
   flips = flips if isinstance(flips, list) and len(flips) == len(st) else [NO_FLIP] * len(st)
   return [[f, d, fl] for (f, d), fl in zip(st, flips)]


def flips(asset: JsonDict, n: int = 0) -> list[int]:
   """!Each step's mirroring (I3; 0 none, 1 horizontal, 2 vertical, 3 both).
   @param asset  sprite asset
   @param n      animation index
   @return one value per step
   """
   return [s[FLIP_FIELD] for s in _steps3(asset, n)]


def _store(asset: JsonDict, n: int, st: Sequence[Step]) -> None:
   """!Writes steps back: "period" when every step has the same duration
   (smaller and simpler), "durations" otherwise; I3: "flips" when a step is
   mirrored (internal steps carry them). Other keys (loop) stay.
   @param asset  sprite asset
   @param n      animation index
   @param st     list of [frame, duration] or [frame, duration, flips]
   @return None
   """
   a = animation(asset, n)
   a["frames"] = [s[0] for s in st]
   a.pop("period", None)
   a.pop("durations", None)
   durations = [s[1] for s in st]
   if durations and len(set(durations)) == 1:
      a["period"] = durations[0]
   else:
      a["durations"] = durations
   mirrored = [s[FLIP_FIELD] if len(s) > FLIP_FIELD else NO_FLIP for s in st]
   if any(mirrored):
      a["flips"] = mirrored
   else:
      a.pop("flips", None)


def _gc_frames(asset: JsonDict) -> None:
   """!Drops frames no animation shows and renumbers the rest.
   @param asset  sprite asset
   @return None
   """
   frames = asset.get("frames", [])
   anims = asset.get("animations", [])
   used = sorted({f for a in anims for f in a.get("frames", []) if isinstance(f, int)})
   if used == list(range(len(frames))):
      return
   remap = {old: new for new, old in enumerate(used)}
   asset["frames"] = [frames[i] for i in used if i < len(frames)]
   for a in anims:
      a["frames"] = [remap[f] for f in a.get("frames", []) if f in remap]


def _check_steps(st: Sequence[Step]) -> None:
   """!Refuses animations longer than the engine allows.
   @param st  steps
   @return None
   """
   if len(st) > MAX_STEPS:
      raise ValueError(f"an animation has at most {MAX_STEPS} steps")


def add_images(doc: Document, key: str, images: Sequence[RgbaImage], anim: int = 0, at: int | None = None,
               duration: int = DEFAULT_DURATION, folder: str | None = None,
               names: Sequence[str] | None = None) -> list[int]:
   """!Adds images as new frames, each shown by a new step.
   @param doc       Document
   @param key       sprite key
   @param images    list of (w, h, RGBA), each exactly the sprite's size
                    (see imaging.prepare())
   @param anim      animation index
   @param at        step index to insert at, or None for the end
   @param duration  duration of the new steps
   @param folder    folder for the image files, default "frames/<sprite name>"
   @param names     file name stems per image, default "<sprite name>_<n>"
   @return list of the new steps' indices
   """
   asset = doc.get(key)
   w, h = asset["width"], asset["height"]
   # "sprite:HERO WALK" -> "hero_walk"
   slug = key.split(":", 1)[-1].strip().lower().replace(" ", "_") or "sprite"
   folder = folder or f"frames/{slug}"
   st = _steps3(asset, anim) if asset.get("frames") else []
   at = len(st) if at is None else max(0, min(at, len(st)))
   new_steps = []
   for i, img in enumerate(images):
      if img[:IMAGE_SIZE_FIELDS] != (w, h):
         raise ValueError(f"image {i} is {img[0]}x{img[1]}, the sprite is {w}x{h}")
      stem = names[i] if names else f"{slug}_{len(asset['frames'])}"
      rel = doc.unique_image_path(folder, stem)
      doc.add_image(rel, img)
      asset["frames"].append({"image": rel})
      new_steps.append([len(asset["frames"]) - 1, duration, NO_FLIP])
   st[at:at] = new_steps
   _check_steps(st)
   _store(asset, anim, st)
   return list(range(at, at + len(new_steps)))


def replace_image(doc: Document, key: str, frame: int, image: RgbaImage, stem: str | None = None) -> None:
   """!Gives a frame a new image (every step showing it changes).
   @param doc    Document
   @param key    sprite key
   @param frame  frame index
   @param image  (w, h, RGBA) of the sprite's size
   @param stem   file name stem, or None to derive one
   @return None
   """
   asset = doc.get(key)
   if image[:IMAGE_SIZE_FIELDS] != (asset["width"], asset["height"]):
      raise ValueError("image does not match the sprite size")
   slug = key.split(":", 1)[-1].strip().lower().replace(" ", "_") or "sprite"
   rel = doc.unique_image_path(f"frames/{slug}", stem or f"{slug}_{frame}")
   doc.add_image(rel, image)
   asset["frames"][frame] = {"image": rel}


def set_durations(doc: Document, key: str, rows: Iterable[int], duration: int, anim: int = 0) -> None:
   """!Sets the duration of some steps.
   @param doc       Document
   @param key       sprite key
   @param rows      step indices
   @param duration  1-255 display frames
   @param anim      animation index
   @return None
   """
   if not 1 <= duration <= MAX_DURATION:
      raise ValueError(f"duration must be 1-{MAX_DURATION}")
   asset = doc.get(key)
   st = _steps3(asset, anim)
   for r in rows:
      st[r][1] = duration
   _store(asset, anim, st)


def duplicate_steps(doc: Document, key: str, rows: Iterable[int], anim: int = 0) -> list[int]:
   """!Repeats steps right after the last one (same frame, no new tiles).
   @param doc   Document
   @param key   sprite key
   @param rows  step indices
   @param anim  animation index
   @return indices of the copies
   """
   asset = doc.get(key)
   st = _steps3(asset, anim)
   rows = sorted(set(rows))
   copies = [list(st[r]) for r in rows]
   at = rows[-1] + 1
   st[at:at] = copies
   _check_steps(st)
   _store(asset, anim, st)
   return list(range(at, at + len(copies)))


def remove_steps(doc: Document, key: str, rows: Iterable[int], anim: int = 0) -> None:
   """!Removes steps; frames no animation shows any more are dropped.
   @param doc   Document
   @param key   sprite key
   @param rows  step indices
   @param anim  animation index
   @return None
   """
   asset = doc.get(key)
   drop = set(rows)
   st = [s for i, s in enumerate(_steps3(asset, anim)) if i not in drop]
   _store(asset, anim, st)
   _gc_frames(asset)


def move_steps(doc: Document, key: str, rows: Iterable[int], delta: int, anim: int = 0) -> list[int]:
   """!Moves a block of steps earlier (delta < 0) or later.
   @param doc    Document
   @param key    sprite key
   @param rows   step indices
   @param delta  places to move
   @param anim   animation index
   @return the steps' new indices
   """
   asset = doc.get(key)
   st = _steps3(asset, anim)
   rows = sorted(set(rows))
   picked = [st[r] for r in rows]
   rest = [s for i, s in enumerate(st) if i not in set(rows)]
   at = max(0, min(len(rest), rows[0] + delta))
   rest[at:at] = picked
   _store(asset, anim, rest)
   return list(range(at, at + len(picked)))


def set_loop(doc: Document, key: str, loop: bool, anim: int = 0) -> None:
   """!Whether an animation loops (or holds its last step).
   @param doc   Document
   @param key   sprite key
   @param loop  True to loop
   @param anim  animation index
   @return None
   """
   a = animation(doc.get(key), anim)
   if loop:
      a.pop("loop", None)   # looping is the default
   else:
      a["loop"] = False


def add_animation(doc: Document, key: str, copy_from: int | None = None) -> int:
   """!Adds an animation.
   @param doc        Document
   @param key        sprite key
   @param copy_from  animation index to copy, or None to start with frame 0
   @return the new animation's index
   """
   asset = doc.get(key)
   if not asset.get("animations"):   # the compiler's default, made explicit
      asset["animations"] = [{"frames": [0] if asset.get("frames") else [], "period": 1}]
   anims = asset["animations"]
   if copy_from is not None and 0 <= copy_from < len(anims):
      anims.append(dict(anims[copy_from], frames=list(anims[copy_from]["frames"])))
      for k in ("durations", "flips"):   # lists of their own (I3: flips too)
         if k in anims[-1]:
            anims[-1][k] = list(anims[-1][k])
   else:
      anims.append({"frames": [0] if asset.get("frames") else [], "period": DEFAULT_DURATION})
   return len(anims) - 1


def remove_animation(doc: Document, key: str, anim: int) -> None:
   """!Removes an animation (a sprite keeps at least one).
   @param doc   Document
   @param key   sprite key
   @param anim  animation index
   @return None
   """
   asset = doc.get(key)
   anims = asset.get("animations", [])
   if len(anims) <= 1:
      raise ValueError("a sprite needs at least one animation")
   del anims[anim]
   _gc_frames(asset)


def set_flips(doc: Document, key: str, rows: Iterable[int], value: int, anim: int = 0) -> None:
   """!Mirrors some steps (I3: 0 none, 1 horizontal, 2 vertical, 3 both; the engine's asset_compiler.MAX_FLIP).
   @param doc    Document
   @param key    sprite key
   @param rows   step indices
   @param value  0-3
   @param anim   animation index
   @return None
   """
   most = engine.asset_compiler().MAX_FLIP
   if not isinstance(value, int) or isinstance(value, bool) or not NO_FLIP <= value <= most:
      raise ValueError(f"a step's flips are {NO_FLIP}-{most} (1 horizontal, 2 vertical)")
   asset = doc.get(key)
   st = _steps3(asset, anim)
   for r in rows:
      st[r][FLIP_FIELD] = value
   _store(asset, anim, st)


def set_stream(doc: Document, key: str, on: bool) -> None:
   """!Whether a sprite is streamed (I3: only the shown frame is in its slot's tiles, uploaded when the frame
   changes, so its frames together may use more tiles than a slot holds; one frame must fit).
   @param doc  Document
   @param key  sprite key
   @param on   True or False
   @return None
   """
   asset = doc.get(key)
   if on:
      asset["stream"] = True
   else:
      asset.pop("stream", None)


def step_table(asset: JsonDict) -> list[int] | None:
   """!A sprite's step table (I3, asset::Sprite::steps): [first stand, second stand, after second, after first]
   entries of its walk animations.
   @param asset  sprite asset
   @return the four entries, or None
   """
   t = asset.get("steps")
   return list(t) if isinstance(t, list) else None


def set_step_table(doc: Document, key: str, table: Sequence[int] | None) -> None:
   """!Sets a sprite's step table (I3): the walk animations pause on one of two standing entries between steps and
   a new step starts at the entry after the other, so the feet alternate (capsule/field/field.h).
   @param doc    Document
   @param key    sprite key
   @param table  [first stand, second stand, after second, after first] (animation entries), or None
   @return None
   """
   ac = engine.asset_compiler()
   asset = doc.get(key)
   if table is None:
      asset.pop("steps", None)
      return
   if len(table) != ac.STEP_ENTRIES or any(not isinstance(v, int) or isinstance(v, bool) or
                                           not 0 <= v <= ac.MAX_ANIM_FRAMES for v in table):
      raise ValueError(f"a step table has {ac.STEP_ENTRIES} animation entries, 0-{ac.MAX_ANIM_FRAMES}")
   asset["steps"] = list(table)


def sheet_frame_count(path: str | Path, w: int, h: int) -> int:
   """!How many frames of a sprite's size an indexed sheet holds (in reading order; I3).
   @param path  the palette PNG
   @param w     frame width
   @param h     frame height
   @return the count
   """
   bm = engine.bitmap()
   try:
      iw, ih, _idx = bm.read_png_indices(path)
   except bm.BitmapError as e:
      raise ValueError(str(e)) from None
   if iw % w or ih % h:
      raise ValueError(f"{Path(path).name} is {iw}x{ih}, not a sheet of {w}x{h} frames")
   return (iw // w) * (ih // h)


def add_sheet_frames(doc: Document, key: str, source: str | Path, anim: int = 0,
                     duration: int = DEFAULT_DURATION) -> list[int]:
   """!Adds every frame of an indexed sheet (I3: a palette PNG of frames of the sprite's size, read in reading
   order, its palette indices used as they are) as new frames, each shown by a new step. The sheet is copied next
   to the manifest at once (frames/SPRITE/NAME.png; the compiler reads indexed frames from files).
   @param doc       Document (saved: its folder is needed)
   @param key       sprite key
   @param source    the palette PNG
   @param anim      animation index
   @param duration  duration of the new steps
   @return the new steps' indices
   """
   if doc.base_dir is None:
      raise ValueError("save the manifest first: an indexed sheet is copied next to it")
   asset = doc.get(key)
   if asset.get("palette") == "auto":
      raise ValueError("indexed frames keep their palette indices: give the sprite a palette of its own first")
   n = sheet_frame_count(source, asset["width"], asset["height"])
   slug = key.split(":", 1)[-1].strip().lower().replace(" ", "_") or "sprite"
   rel = doc.unique_image_path(f"frames/{slug}", Path(source).stem)
   out = doc.base_dir / rel
   out.parent.mkdir(parents=True, exist_ok=True)
   out.write_bytes(Path(source).read_bytes())   # as it is: the indices are the data
   st = _steps3(asset, anim) if asset.get("frames") else []
   first = len(st)
   for k in range(n):
      asset["frames"].append({"image": rel, "frame": k, "indexed": True})
      st.append([len(asset["frames"]) - 1, duration, NO_FLIP])
   _check_steps(st)
   _store(asset, anim, st)
   return list(range(first, first + n))


def resize(doc: Document, key: str, w: int, h: int) -> None:
   """!Changes the sprite size, refitting image frames by centring them.
   Shape frames keep their coordinates.
   @param doc  Document
   @param key  sprite key
   @param w    new width (an OBJ size)
   @param h    new height
   @return None
   """
   if (w, h) not in SPRITE_SIZES:
      raise ValueError(f"{w}x{h} is not a sprite size")
   asset = doc.get(key)
   if any(isinstance(f, dict) and f.get("indexed") for f in asset.get("frames", [])):
      raise ValueError("a sprite of indexed sheet frames keeps its size (its sheet's frames are that size)")
   for i, f in enumerate(asset.get("frames", [])):
      if "image" in f:
         img = doc.image(f["image"])
         if img is not None:
            stem = f["image"].rsplit("/", 1)[-1].rsplit(".", 1)[0]   # file name without folder and extension
            asset["width"], asset["height"] = w, h   # replace_image() checks against the new size
            replace_image(doc, key, i, imaging.center(img, w, h), stem)
   asset["width"], asset["height"] = w, h


def timeline(asset: JsonDict, anim: int = 0, loops: int = 1) -> list[int]:
   """!Which frame shows on each display frame, as the engine plays it
   (gfx::sprites::update(): each step shows for its duration; a looping
   animation restarts, otherwise the last step holds).
   @param asset  sprite asset
   @param anim   animation index
   @param loops  times through a looping animation
   @return list of frame indices, one per display frame
   """
   st = steps(asset, anim)
   if not st:
      return []
   anims = asset.get("animations") or [{}]   # read only: never adds keys
   out = []
   for _ in range(loops if anims[min(anim, len(anims) - 1)].get("loop", True) else 1):
      for f, d in st:
         out += [f] * d
   return out


def total_duration(asset: JsonDict, anim: int = 0) -> int:
   """!Length of one pass of an animation.
   @param asset  sprite asset
   @param anim   animation index
   @return display frames
   """
   return sum(d for _, d in steps(asset, anim))


def frame_pixels(compiled: JsonDict, frame: int) -> tuple[int, int, bytes]:
   """!Decodes a compiled frame back to palette indices, exactly as the GBA
   will show it (works for shape and image frames alike).
   @param compiled  the sprite's AssetReport.compiled
   @param frame     frame index
   @return (w, h, bytes of indices)
   """
   ac = engine.asset_compiler()
   shape, size = compiled["shape"], compiled["size"]
   w, h = next(k for k, v in ac.OBJ_SIZES.items() if v == (shape, size))
   tw, th = w // TILE, h // TILE
   words = compiled["tiles"]

   # Frames are stored one after another, their tiles in reading order.
   base = frame * tw * th * WORDS_PER_TILE
   out = bytearray(w * h)
   for ty in range(th):
      for tx in range(tw):
         t = base + (ty * tw + tx) * WORDS_PER_TILE
         for row in range(TILE):
            word = words[t + row]
            for x in range(TILE):
               # 4bpp: the leftmost pixel is in the word's lowest bits.
               out[(ty * TILE + row) * w + tx * TILE + x] = (word >> (BITS_PER_PIXEL * x)) & PIXEL_MASK
   return w, h, bytes(out)


def palette_rgb(compiled: JsonDict) -> list[Color5]:
   """!The compiled palette as 5-bit colors (entries 1-15).
   @param compiled  the sprite's AssetReport.compiled
   @return list of 15 (r5, g5, b5)
   """
   return [(c & CHANNEL_MASK, c >> GREEN_SHIFT & CHANNEL_MASK, c >> BLUE_SHIFT & CHANNEL_MASK)
           for c in compiled["palette"][1:1 + PALETTE_COLORS]]
