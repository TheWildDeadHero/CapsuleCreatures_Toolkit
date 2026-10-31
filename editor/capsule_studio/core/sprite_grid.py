"""![S3] Direction-grid sprite sheets (D-30 section 3, engine DS1: "layout": "direction_grid").

A grid sprite's frames are a grid: columns are directions in the field's order down, up, left and, optionally,
right; rows are named animation frames ("rows": ["stand", "step_a", ...]; every direction has the same rows). With
three columns the right-facing frames are the left column mirrored horizontally, so no right-facing pixels are
stored. "grid" is an indexed sheet ({"image", "indexed": true}: frames of the sprite's size, "columns" across, one
row per row name) or rows of frame objects ([[down, up, left(, right)], ...]). Each animation {"rows": [row names],
"period" | "durations", "loop"} becomes the four directions' animations (down, up, left, right), or one with
"direction". The engine's asset_compiler (expand_grid(), compile_grid_sprite()) decides what is valid, merges
identical frames and says what the grid saves ("grid_saved", bytes).

Changing the columns or the rows of a sheet grid rewrites its palette PNG (core.indexed_png: every pixel keeps its
index) as a new file beside the manifest at once; the manifest change is one undo step.

Functions that change a Document must run inside its edit(). Nothing here imports Qt.
"""
from __future__ import annotations

import copy
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import engine, imaging, indexed_png

if TYPE_CHECKING:
   from .document import AssetReport, Document
   from .imaging import RgbaImage

## A parsed JSON object (an asset, an animation, a frame).
JsonDict = dict[str, Any]

## Animation keys copied into each direction's animation (asset_compiler GRID_ANIM_KEYS without rows / direction).
TIMING_KEYS = ("period", "durations", "loop")
## Display frames a new grid animation's rows show (its "period").
NEW_PERIOD = 8
## Frame size of a new grid (an NPC's, width x height).
NEW_GRID_SIZE = (16, 32)
## Rows a new grid has.
NEW_ROWS = ("stand", "step_a", "step_b")
## Colors of a new grid's palette (hex RGB): skin, cloth, dark cloth, outline.
NEW_PALETTE = ("#f0c8a0", "#3060c0", "#203070", "#202020")
## Shapes whose "x" and "w" a horizontal mirror moves (x -> width - x - w).
BOX_SHAPES = ("rect", "frame", "vgradient", "stripes", "checker", "dots")
## Shapes whose "cx" a horizontal mirror moves (cx -> width - 1 - cx).
ROUND_SHAPES = ("circle", "ring", "ellipse")
## A frame's mirroring in a compiled animation step: none, horizontal (asset::kFlipH).
NO_FLIP, FLIP_H = 0, 1
## Folder below the manifest rewritten grid sheets go to.
SHEET_FOLDER = "frames"


def _ac() -> Any:
   """!The engine's asset compiler.
   @return module
   """
   return engine.asset_compiler()


def layout_word() -> str:
   """!The layout value of a grid sprite (asset_compiler DIRECTION_GRID).
   @return "direction_grid"
   """
   return str(_ac().DIRECTION_GRID)


def directions() -> list[str]:
   """!The grid's columns in order (asset_compiler DIRECTIONS: capsule::field::Direction order).
   @return down, up, left, right
   """
   return list(_ac().DIRECTIONS)


def mirrored_columns() -> int:
   """!Columns of a grid whose right column mirrors the left (asset_compiler GRID_MIRRORED_COLUMNS).
   @return 3
   """
   return int(_ac().GRID_MIRRORED_COLUMNS)


def mirrored_from() -> int:
   """!The column a missing right column mirrors (asset_compiler MIRRORED_FROM: left).
   @return its index
   """
   return int(_ac().MIRRORED_FROM)


def is_grid(asset: JsonDict | None) -> bool:
   """!Whether a sprite's frames are a direction grid.
   @param asset  sprite asset, or None
   @return True for "layout": "direction_grid"
   """
   return isinstance(asset, dict) and asset.get("layout") == layout_word()


def is_sheet(asset: JsonDict) -> bool:
   """!Whether a grid is an indexed sheet (else rows of frame objects).
   @param asset  grid sprite
   @return True for {"image", "indexed"}
   """
   return isinstance(asset.get("grid"), dict)


def columns(asset: JsonDict) -> int:
   """!A grid's stored columns.
   @param asset  grid sprite
   @return 3 (right mirrors left) or 4
   """
   if is_sheet(asset):
      return int(asset.get("columns", mirrored_columns()))
   g = asset.get("grid")
   return len(g[0]) if isinstance(g, list) and g and isinstance(g[0], list) else mirrored_columns()


def right_mirrors_left(asset: JsonDict) -> bool:
   """!Whether a grid stores no right column (the left one mirrored is shown).
   @param asset  grid sprite
   @return True with three columns
   """
   return columns(asset) == mirrored_columns()


def rows(asset: JsonDict) -> list[str]:
   """!A grid's row names.
   @param asset  grid sprite
   @return names, top row first
   """
   r = asset.get("rows")
   return [str(n) for n in r] if isinstance(r, list) else []


def animations(asset: JsonDict) -> list[JsonDict]:
   """!A grid's animations (each by rows).
   @param asset  grid sprite
   @return the manifest's own list
   """
   a = asset.get("animations")
   return a if isinstance(a, list) else []


def _check(doc: Document, asset: JsonDict) -> AssetReport:
   """!Compiles a grid sprite with the engine's compiler.
   @param doc    asset manifest Document
   @param asset  the sprite
   @return the report
   @throws ValueError with the compiler's message
   """
   report = doc.compile_asset(asset)
   if not report.ok:
      raise ValueError(report.error)
   return report


def _edit(doc: Document, key: str, change: Any) -> None:
   """!Changes a copy of a grid sprite, checks it with the compiler and stores it.
   @param doc     asset manifest Document
   @param key     sprite key
   @param change  callable(asset copy) -> None
   @return None
   """
   a = doc.get(key)
   if not is_grid(a):
      raise ValueError(f"{key} is not a direction grid")
   b = copy.deepcopy(a)
   change(b)
   _check(doc, b)
   a.clear()
   a.update(b)


def new_grid(doc: Document, key: str, width: int, height: int, row_names: Sequence[str] = NEW_ROWS,
             mirror: bool = True, index: int | None = None) -> JsonDict:
   """!Adds a grid sprite of empty shape frames (draw or import its frames after): one row per name, three columns
   (right mirrors left) or four, a standing animation of the first row and a walk through the others.
   @param doc        asset manifest Document
   @param key        "sprite:NAME"
   @param width      frame width (an OBJ size)
   @param height     frame height
   @param row_names  the rows
   @param mirror     three columns (right mirrors left), else four
   @param index      position in the manifest, or None for the end
   @return the asset
   """
   cols = mirrored_columns() if mirror else len(directions())
   names = list(row_names)
   a: JsonDict = {"key": key, "kind": "sprite", "width": width, "height": height, "palette": list(NEW_PALETTE),
                  "layout": layout_word(), "rows": names,
                  "grid": [[{"shapes": []} for _ in range(cols)] for _ in names],
                  "animations": [{"rows": names[:1], "period": 1}]}
   if len(names) > 1:
      a["animations"].append({"rows": names[1:] + names[:1], "period": NEW_PERIOD})
   _check(doc, a)
   return doc.add_asset(a, index)


def _mirror_shape(s: JsonDict, width: int) -> JsonDict:
   """!A shape mirrored horizontally inside a frame (polygons and unknown shapes are copied as they are).
   @param s      the shape
   @param width  the frame's width
   @return the mirrored shape
   """
   out = copy.deepcopy(s)
   kind = s.get("shape")
   if kind in BOX_SHAPES and isinstance(s.get("x"), int) and isinstance(s.get("w"), int):
      out["x"] = width - s["x"] - s["w"]
   elif kind in ROUND_SHAPES and isinstance(s.get("cx"), int):
      out["cx"] = width - 1 - s["cx"]   # pixel columns mirror as x -> width - 1 - x
   elif kind == "hgradient" and isinstance(s.get("colors"), list):
      out["x"] = width - s.get("x", 0) - s.get("w", width)
      out["colors"] = list(reversed(s["colors"]))
   return out


def _mirror_frame(doc: Document, frame: Any, width: int) -> Any:
   """!A frame object for a right column made from a left one: shapes mirrored, an image frame mirrored into a new
   unsaved image; an indexed sheet frame is copied as it is (mirror it in the sheet).
   @param doc    asset manifest Document
   @param frame  the left frame
   @param width  the frame's width
   @return the right frame
   """
   if isinstance(frame, dict) and isinstance(frame.get("shapes"), list):
      return dict(copy.deepcopy(frame), shapes=[_mirror_shape(s, width) for s in frame["shapes"]])
   if isinstance(frame, dict) and "image" in frame and not frame.get("indexed"):
      img = doc.image(frame["image"])
      if img is not None:
         rel = doc.unique_image_path(SHEET_FOLDER, Path(frame["image"]).stem + "_right")
         doc.add_image(rel, imaging.mirror(img))
         return dict(copy.deepcopy(frame), image=rel)
   return copy.deepcopy(frame)


def _sheet(doc: Document, asset: JsonDict) -> tuple[Path, int, int, bytearray]:
   """!A sheet grid's palette PNG.
   @param doc    asset manifest Document
   @param asset  grid sprite
   @return (path, width, height, indices)
   """
   if doc.base_dir is None:
      raise ValueError("save the manifest first: its grid sheet is beside it")
   path = (doc.base_dir / asset["grid"]["image"]).resolve()
   w, h, px = indexed_png.read(path)
   return path, w, h, px


def _rewrite_sheet(doc: Document, asset: JsonDict, cells: list[list[Any]], cols: int) -> str:
   """!Writes a new grid sheet (same palette) from frame blocks and points the grid at it.
   @param doc    asset manifest Document
   @param asset  grid sprite (its copy being changed)
   @param cells  rows of frame blocks (each the frame's rows of indices; None: an empty frame)
   @param cols   columns of the new sheet
   @return the new manifest path
   """
   path, _w, _h, _px = _sheet(doc, asset)
   fw, fh = asset["width"], asset["height"]
   out = bytearray(fw * cols * fh * len(cells))
   for r, row in enumerate(cells):
      for c, block in enumerate(row):
         for y in range(fh):
            o = (r * fh + y) * fw * cols + c * fw
            out[o:o + fw] = block[y] if block is not None else bytes(fw)
   plte, trns = indexed_png.palette_chunks(path)
   rel = doc.unique_image_path(str(Path(asset["grid"]["image"]).parent.as_posix()), path.stem + "_grid")
   target = doc.base_dir / rel
   target.parent.mkdir(parents=True, exist_ok=True)
   target.write_bytes(indexed_png.encode(fw * cols, fh * len(cells), out, plte, trns))
   asset["grid"] = dict(asset["grid"], image=rel)
   return rel


def _blocks(doc: Document, asset: JsonDict) -> list[list[list[bytes]]]:
   """!A sheet grid's frames as blocks of index rows.
   @param doc    asset manifest Document
   @param asset  grid sprite
   @return [row][column] -> the frame's rows (bytes of indices)
   """
   _path, w, h, px = _sheet(doc, asset)
   fw, fh = asset["width"], asset["height"]
   cols = columns(asset)
   if w < fw * cols or h < fh * len(rows(asset)):
      raise ValueError(f"the grid sheet is {w}x{h}, smaller than {cols} x {len(rows(asset))} frames of {fw}x{fh}")
   return [[[bytes(px[(r * fh + y) * w + c * fw:(r * fh + y) * w + (c + 1) * fw]) for y in range(fh)]
            for c in range(cols)] for r in range(len(rows(asset)))]


def set_right_mirrors_left(doc: Document, key: str, on: bool) -> int:
   """!Three columns (the right frames are the left ones mirrored, none stored) or four (a stored right column,
   made from the left ones mirrored). A sheet grid's PNG is rewritten.
   @param doc  asset manifest Document
   @param key  sprite key
   @param on   right mirrors left
   @return right frames dropped that were not the left ones mirrored (their pixels are gone; 0 when adding)
   """
   lost = {"n": 0}

   def change(a: JsonDict) -> None:
      if right_mirrors_left(a) == on:
         return
      right = len(directions()) - 1
      if is_sheet(a):
         blocks = _blocks(doc, a)
         if on:
            lost["n"] = sum(1 for row in blocks if row[right] != [line[::-1] for line in row[mirrored_from()]])
            blocks = [row[:mirrored_columns()] for row in blocks]
            a.pop("columns", None)
         else:
            blocks = [row + [[line[::-1] for line in row[mirrored_from()]]] for row in blocks]
            a["columns"] = len(directions())
         _rewrite_sheet(doc, a, blocks, len(blocks[0]))
      elif on:
         lost["n"] = len(a["grid"])
         a["grid"] = [row[:mirrored_columns()] for row in a["grid"]]
      else:
         a["grid"] = [row + [_mirror_frame(doc, row[mirrored_from()], a["width"])] for row in a["grid"]]
   _edit(doc, key, change)
   return lost["n"]


def rename_row(doc: Document, key: str, old: str, new: str) -> None:
   """!Renames a row; the animations naming it follow.
   @param doc  asset manifest Document
   @param key  sprite key
   @param old  its name
   @param new  the new name
   @return None
   """
   def change(a: JsonDict) -> None:
      names = rows(a)
      if old not in names:
         raise ValueError(f"no row {old!r} (rows: {', '.join(names)})")
      if new in names and new != old:
         raise ValueError(f"the grid has a row {new!r} already")
      a["rows"] = [new if n == old else n for n in names]
      for an in animations(a):
         an["rows"] = [new if n == old else n for n in an.get("rows", [])]
   _edit(doc, key, change)


def add_row(doc: Document, key: str, name: str, copy_of: str | None = None) -> None:
   """!Adds a row at the bottom, a copy of another (default the last); a sheet grid's PNG is rewritten.
   @param doc      asset manifest Document
   @param key      sprite key
   @param name     the new row's name
   @param copy_of  the row copied, or None for the last
   @return None
   """
   def change(a: JsonDict) -> None:
      names = rows(a)
      if name in names:
         raise ValueError(f"the grid has a row {name!r} already")
      src = names.index(copy_of) if copy_of is not None else len(names) - 1
      if is_sheet(a):
         blocks = _blocks(doc, a)
         _rewrite_sheet(doc, a, blocks + [copy.deepcopy(blocks[src])], columns(a))
      else:
         a["grid"].append(copy.deepcopy(a["grid"][src]))
      a["rows"] = names + [name]
   _edit(doc, key, change)


def remove_row(doc: Document, key: str, name: str) -> None:
   """!Removes a row (refused while an animation shows only it); animations drop it; a sheet grid's PNG is
   rewritten.
   @param doc   asset manifest Document
   @param key   sprite key
   @param name  the row
   @return None
   """
   def change(a: JsonDict) -> None:
      names = rows(a)
      if name not in names:
         raise ValueError(f"no row {name!r}")
      i = names.index(name)
      for k, an in enumerate(animations(a)):
         kept = [n for n in an.get("rows", []) if n != name]
         if not kept:
            raise ValueError(f"animation {k} shows only row {name!r}; change it first")
         if "durations" in an:   # each row step has its own duration: drop those of the removed row
            an["durations"] = [d for n, d in zip(an.get("rows", []), an["durations"]) if n != name]
         an["rows"] = kept
      if is_sheet(a):
         blocks = _blocks(doc, a)
         _rewrite_sheet(doc, a, blocks[:i] + blocks[i + 1:], columns(a))
      else:
         del a["grid"][i]
      a["rows"] = names[:i] + names[i + 1:]
   _edit(doc, key, change)


def move_row(doc: Document, key: str, name: str, delta: int) -> None:
   """!Moves a row up (delta -1) or down (+1); a sheet grid's PNG is rewritten.
   @param doc    asset manifest Document
   @param key    sprite key
   @param name   the row
   @param delta  -1 or +1
   @return None
   """
   def change(a: JsonDict) -> None:
      names = rows(a)
      i = names.index(name)
      j = i + delta
      if not 0 <= j < len(names):
         return
      order = list(range(len(names)))
      order[i], order[j] = order[j], order[i]
      if is_sheet(a):
         blocks = _blocks(doc, a)
         _rewrite_sheet(doc, a, [blocks[k] for k in order], columns(a))
      else:
         a["grid"] = [a["grid"][k] for k in order]
      a["rows"] = [names[k] for k in order]
   _edit(doc, key, change)


def add_animation(doc: Document, key: str, row_names: Sequence[str], period: int | None = NEW_PERIOD,
                  durations: Sequence[int] | None = None, loop: bool | None = None,
                  direction: str | None = None) -> int:
   """!Adds an animation by rows.
   @param doc        asset manifest Document
   @param key        sprite key
   @param row_names  the rows it shows, in order
   @param period     display frames per row step, or None (durations given)
   @param durations  display frames per row step, or None
   @param loop       loop (None: the compiler's default)
   @param direction  one direction only, or None for all four
   @return its index
   """
   an: JsonDict = {"rows": list(row_names)}
   for k, v in (("period", period if durations is None else None), ("durations", durations), ("loop", loop),
                ("direction", direction)):
      if v is not None:
         an[k] = list(v) if k == "durations" else v
   out = {"i": 0}

   def change(a: JsonDict) -> None:
      a.setdefault("animations", []).append(an)
      out["i"] = len(a["animations"]) - 1
   _edit(doc, key, change)
   return out["i"]


def set_animation(doc: Document, key: str, index: int, **fields: Any) -> None:
   """!Changes an animation's rows, period, durations (giving one drops the other), loop or direction (None
   removes a field: all four directions, the compiler's loop default).
   @param doc     asset manifest Document
   @param key     sprite key
   @param index   the animation
   @param fields  rows, period, durations, loop, direction
   @return None
   """
   allowed = set(_ac().GRID_ANIM_KEYS)
   bad = sorted(set(fields) - allowed)
   if bad:
      raise ValueError(f"a grid animation has {', '.join(sorted(allowed))}, not {', '.join(bad)}")

   def change(a: JsonDict) -> None:
      an = animations(a)[index]
      for k, v in fields.items():
         if v is None:
            an.pop(k, None)
         else:
            an[k] = list(v) if isinstance(v, (list, tuple)) else v
      if fields.get("durations") is not None:
         an.pop("period", None)
      if fields.get("period") is not None:
         an.pop("durations", None)
   _edit(doc, key, change)


def remove_animation(doc: Document, key: str, index: int) -> None:
   """!Removes an animation (a grid keeps one).
   @param doc    asset manifest Document
   @param key    sprite key
   @param index  the animation
   @return None
   """
   def change(a: JsonDict) -> None:
      if len(animations(a)) <= 1:
         raise ValueError("a sprite keeps one animation")
      del a["animations"][index]
   _edit(doc, key, change)


def expansion(asset: JsonDict) -> list[tuple[int, str]]:
   """!Which grid animation and direction each animation of the compiled sprite plays (expand_grid()'s order:
   every grid animation in turn, its four directions down, up, left, right, or its one direction).
   @param asset  grid sprite
   @return [(grid animation index, direction)] by compiled animation index
   """
   out = []
   anims = animations(asset) or [{"rows": rows(asset)[:1]}]
   for i, an in enumerate(anims):
      for d in ([an["direction"]] if "direction" in an else directions()):
         out.append((i, d))
   return out


def compiled_index(asset: JsonDict, anim: int, direction: str) -> int | None:
   """!The compiled sprite's animation that plays a grid animation in a direction.
   @param asset      grid sprite
   @param anim       grid animation index
   @param direction  the direction
   @return its index, or None (the animation has another single direction)
   """
   for k, (i, d) in enumerate(expansion(asset)):
      if i == anim and d == direction:
         return k
   return None


def timeline(compiled: JsonDict, index: int, loops: int = 1) -> list[tuple[int, int]]:
   """!What a compiled sprite's animation shows on each display frame, as gfx::sprites::update() plays it (each
   entry for its duration; a looping one restarts).
   @param compiled  compile_sprite() / compile_grid_sprite() result
   @param index     its animation
   @param loops     times through a looping animation
   @return [(frame, flips)] per display frame
   """
   frames, period, loop, durations, flips = compiled["animations"][index]
   flips = flips or [NO_FLIP] * len(frames)
   one = []
   for k, f in enumerate(frames):
      one += [(f, flips[k])] * (durations[k] if durations else period)
   return one * (loops if loop else 1)


def cell_frames(doc: Document, key: str) -> tuple[JsonDict | None, str | None]:
   """!Every grid cell's frame drawn by the engine's compiler, before identical frames merge (frame r * columns + c is
   row r, column c).
   @param doc  asset manifest Document
   @param key  sprite key
   @return (compile_sprite() result of the grid's frames, or None; the error or None)
   """
   ac = _ac()
   a = doc.get(key)
   try:
      plain, _cols, _rows = ac.expand_grid(copy.deepcopy(a), key)
      return ac.compile_sprite(plain, doc.data.get("palettes", {}), key, doc.base_dir, None, doc.pending), None
   except (ac.ManifestError, KeyError, TypeError, ValueError, OSError) as e:
      return None, str(e)


def frame_image(compiled: JsonDict, frame: int, flip_h: bool = False) -> RgbaImage:
   """!A compiled frame in the sprite's GBA colors (index 0 transparent), mirrored when asked.
   @param compiled  compile_sprite() result
   @param frame     frame index
   @param flip_h    mirror it horizontally (a right frame from the left one)
   @return (w, h, RGBA)
   """
   from . import sprites
   from .mapview import OPAQUE, bgr_to_rgb
   from .preview import BLUE_SHIFT, GREEN_SHIFT
   w, h, idx = sprites.frame_pixels(compiled, frame)
   pal = [bytes(imaging.RGBA_BYTES)] + [bytes(bgr_to_rgb(r | g << GREEN_SHIFT | b << BLUE_SHIFT) + (OPAQUE,))
                       for r, g, b in sprites.palette_rgb(compiled)]
   rows_ = [idx[y * w:(y + 1) * w] for y in range(h)]
   out = bytearray()
   for row in rows_:
      out += b"".join(pal[v] for v in (reversed(row) if flip_h else row))
   return w, h, out


def saved(report: AssetReport) -> int | None:
   """!ROM the grid saves: the right column it does not store and the identical frames merged (grid_saved).
   @param report  the sprite's compile report
   @return bytes, or None when it does not compile
   """
   return report.compiled.get("grid_saved") if report.ok and report.compiled else None


def lines(doc: Document, key: str) -> list[str]:
   """!A grid sprite as text (`sprite grid show`).
   @param doc  asset manifest Document
   @param key  sprite key
   @return lines
   """
   a = doc.get(key)
   if not is_grid(a):
      return [f"{key}: not a direction grid"]
   r = doc.compile_asset(a)
   cols = directions()[:columns(a)]
   if right_mirrors_left(a):
      cols.append(f"{directions()[-1]} (= {directions()[mirrored_from()]} mirrored)")
   out = [f"{key}: {a.get('width')}x{a.get('height')} direction grid, "
          f"{'sheet ' + a['grid'].get('image', '') if is_sheet(a) else 'frame objects'}",
          f"  columns: {', '.join(cols)}", f"  rows: {', '.join(rows(a))}"]
   for i, an in enumerate(animations(a)):
      timing = f"durations {an['durations']}" if "durations" in an else f"period {an.get('period', 1)}"
      where = an.get("direction", "all directions")
      out.append(f"  animation {i}: rows {' '.join(an.get('rows', []))}, {timing}, {where}"
                 + (", once" if an.get("loop") is False else ""))
   if r.ok:
      c = r.compiled
      out.append(f"  compiled: {c['frames']} frames stored, {len(c['animations'])} animations; "
                 f"ROM saved {c.get('grid_saved', 0)} bytes")
   else:
      out.append(f"  error: {r.error}")
   return out
