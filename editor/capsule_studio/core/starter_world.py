"""!The world every new game starts with (D-40 RN): one tileset of simple-shape tiles and one small map, enough
for the game to build and for the map editor to have something to paint with.

  - Tileset "basic": one shape sheet ("shapes", drawn by the engine's compiler from rectangles, a frame and dots;
    no image file) and three metatiles: "ground" (green with darker dots), "path" (sand with darker dots) and
    "wall" (grey stone with a dark frame and seams).
  - Map "start": at least the engine's screen in metatiles, rounded up to whole chunks (16 x 16 on the GBA's
    240 x 160 screen), on the default three tile layers. Its back layer is ground, a path runs across the
    middle row and a wall rings the edge; the wall cells are blocked on the attribute layer. The border (what
    shows outside the map) is wall.
  - The world's start position: the middle of the map, facing down (on the path).

fill() adds these to a world through core.world.Project, core.tilesets and core.maps (the editors' own
functions), unsaved: core.game_world.create() saves them with the world (Project.save_all()). Nothing here
depends on a user interface.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import engine, maps, tilesets
from .document import DocumentError

if TYPE_CHECKING:
   from .world import Project

## The tileset's name in the world (its file: tilesets/basic.json beside the world).
TILESET = "basic"
## The map's name in the world (its file: maps/start.json), also the world's start map.
START_MAP = "start"
## The tileset's one shape sheet.
SHEET = "shapes"

## Colors of the sheet's palette; shapes name them by their place in this list counted from 1 (0 is transparent).
PALETTE = ["#58a838", "#387828", "#d0b070", "#a08048", "#888888", "#505050"]
## Palette entry: ground.
GROUND_COLOR = 1
## Palette entry: the ground's darker dots.
GROUND_DOT_COLOR = 2
## Palette entry: path.
PATH_COLOR = 3
## Palette entry: the path's darker dots.
PATH_DOT_COLOR = 4
## Palette entry: wall stone.
WALL_COLOR = 5
## Palette entry: the wall's frame and seams.
WALL_LINE_COLOR = 6

## Side of a metatile, in pixels (2 x 2 tiles of 8 pixels).
METATILE_PIXELS = tilesets.TILE_PIXELS * tilesets.METATILE_TILES
## The metatiles, left to right on the sheet (one 16 x 16 block each).
GROUND = "ground"
## The path metatile.
PATH = "path"
## The wall metatile.
WALL = "wall"
## Metatile names in sheet order: block column i holds METATILES[i].
METATILES = (GROUND, PATH, WALL)
## The sheet's size in tiles: one block per metatile, one block high.
SHEET_TILES_WIDE = len(METATILES) * tilesets.METATILE_TILES
## Dots drawn on a ground block.
GROUND_DOTS = 8
## Dots drawn on a path block.
PATH_DOTS = 6
## Seeds of the dot patterns (fixed, so every new game gets the same tiles).
GROUND_DOT_SEED = 1
## Seed of the path's dots.
PATH_DOT_SEED = 2
## Side of one dot, in pixels.
DOT_SIZE = 1
## Width of the wall's frame and seams, in pixels.
LINE_WIDTH = 1
## Row of the wall's horizontal seam inside its block (the middle of the block).
SEAM_ROW = METATILE_PIXELS // 2 - LINE_WIDTH
## Columns of the wall's two vertical seams: one in the top half, one in the bottom half (brick courses).
TOP_SEAM_COLUMN = METATILE_PIXELS // 2
## The bottom course's seam column (a quarter of the way in).
BOTTOM_SEAM_COLUMN = METATILE_PIXELS // 4

## Header and constants giving the engine's screen size (hal::video).
VIDEO_HEADER = "capsule/hal/video.h"
## Screen width when the engine's header cannot be read (hal::video::kScreenWidth, the GBA's).
DEFAULT_SCREEN_WIDTH = 240
## Screen height when the engine's header cannot be read (hal::video::kScreenHeight).
DEFAULT_SCREEN_HEIGHT = 160
## The map's tile layer the ground, path and wall are painted on: the back one (BG3 of maps.DEFAULT_LAYERS).
BACK_LAYER = 0
## Attribute collision of a wall cell (0 is passable; the engine blocks any other value).
WALL_COLLISION = 1
## Border size, in metatiles (one wall metatile repeated).
BORDER_SIZE = 1
## The world's start facing.
START_FACING = "down"
## Halves of a size (the map's middle).
HALF = 2


def _block_x(name: str) -> int:
   """!Left edge of a metatile's block on the sheet.
   @param name  one of METATILES
   @return x in pixels
   """
   return METATILES.index(name) * METATILE_PIXELS


def sheet_shapes() -> list[dict[str, Any]]:
   """!The shapes the sheet is drawn from: per metatile block, a filled square and its details.
   @return shape objects (the engine's asset_compiler shapes)
   """
   size = METATILE_PIXELS
   gx, px, wx = _block_x(GROUND), _block_x(PATH), _block_x(WALL)
   return [
      # ground: green, darker dots
      {"shape": "rect", "x": gx, "y": 0, "w": size, "h": size, "color": GROUND_COLOR},
      {"shape": "dots", "x": gx, "y": 0, "w": size, "h": size, "color": GROUND_DOT_COLOR, "count": GROUND_DOTS,
       "seed": GROUND_DOT_SEED, "size": DOT_SIZE},
      # path: sand, darker dots
      {"shape": "rect", "x": px, "y": 0, "w": size, "h": size, "color": PATH_COLOR},
      {"shape": "dots", "x": px, "y": 0, "w": size, "h": size, "color": PATH_DOT_COLOR, "count": PATH_DOTS,
       "seed": PATH_DOT_SEED, "size": DOT_SIZE},
      # wall: grey stone in a dark frame, one horizontal seam and a vertical seam per course (bricks)
      {"shape": "rect", "x": wx, "y": 0, "w": size, "h": size, "color": WALL_COLOR},
      {"shape": "frame", "x": wx, "y": 0, "w": size, "h": size, "color": WALL_LINE_COLOR, "width": LINE_WIDTH},
      {"shape": "rect", "x": wx, "y": SEAM_ROW, "w": size, "h": LINE_WIDTH, "color": WALL_LINE_COLOR},
      {"shape": "rect", "x": wx + TOP_SEAM_COLUMN, "y": 0, "w": LINE_WIDTH, "h": SEAM_ROW, "color": WALL_LINE_COLOR},
      {"shape": "rect", "x": wx + BOTTOM_SEAM_COLUMN, "y": SEAM_ROW, "w": LINE_WIDTH, "h": size - SEAM_ROW,
       "color": WALL_LINE_COLOR},
   ]


def map_size() -> tuple[int, int]:
   """!The map's size: the engine's screen in metatiles, rounded up to whole chunks.
   @return (width, height) in metatiles
   """
   width = engine.header_constant(VIDEO_HEADER, "kScreenWidth", DEFAULT_SCREEN_WIDTH)
   height = engine.header_constant(VIDEO_HEADER, "kScreenHeight", DEFAULT_SCREEN_HEIGHT)

   def chunks(pixels: int) -> int:
      """!Whole chunks covering a screen side.
      @param pixels  screen side
      @return metatiles (a multiple of maps.CHUNK)
      """
      metatiles = -(-pixels // METATILE_PIXELS)   # rounded up
      return -(-metatiles // maps.CHUNK) * maps.CHUNK
   return chunks(width), chunks(height)


def start_position() -> tuple[int, int]:
   """!Where the world starts: the middle of the map (on the path).
   @return (x, y) in metatiles
   """
   width, height = map_size()
   return width // HALF, height // HALF


def _add_tileset(world: Project) -> None:
   """!Adds the tileset: the shape sheet and the metatiles (one undo step on the tileset).
   @param world  the world
   @return None
   """
   ts = world.add_tileset(TILESET)
   with ts.edit("Starter tileset"):
      ts.data["editor"] = {"notes": "New game's tileset: simple shapes drawn by the engine's compiler (no image). "
                                    "Add sheets and metatiles on the Tileset tab, or replace it."}
      ts.data.setdefault("sheets", []).append({"name": SHEET, "palette": list(PALETTE),
                                               "size": [SHEET_TILES_WIDE * tilesets.TILE_PIXELS, METATILE_PIXELS],
                                               "shapes": sheet_shapes()})
      for column, name in enumerate(METATILES):
         tilesets.add_metatile(ts, name, tilesets.block_refs(SHEET, SHEET_TILES_WIDE, column, 0))


def _add_map(world: Project) -> tuple[int, int]:
   """!Adds the map (one undo step on the map; the world gets its start position from Project.add_map()).
   @param world  the world (with the tileset)
   @return the map's (width, height) in metatiles
   """
   width, height = map_size()
   sx, sy = start_position()
   last_x, last_y = width - 1, height - 1
   doc = world.add_map(START_MAP, tilesets=[TILESET])
   with doc.edit("Starter map"):
      doc.data["editor"] = {"notes": "New game's first map: ground in a ring of wall (blocked), a path across the "
                                     "middle where the world starts. Paint it on the Map tab."}
      ground = maps.dictionary_index(doc, f"{TILESET}/{GROUND}")
      path = maps.dictionary_index(doc, f"{TILESET}/{PATH}")
      wall = maps.dictionary_index(doc, f"{TILESET}/{WALL}")
      maps.rect(doc, BACK_LAYER, 0, 0, last_x, last_y, ground)
      maps.rect(doc, BACK_LAYER, 0, sy, last_x, sy, path)
      # The wall ring: top and bottom rows, left and right columns; blocked on the attribute layer.
      for x0, y0, x1, y1 in ((0, 0, last_x, 0), (0, last_y, last_x, last_y), (0, 0, 0, last_y),
                             (last_x, 0, last_x, last_y)):
         maps.rect(doc, BACK_LAYER, x0, y0, x1, y1, wall)
         maps.rect_attributes(doc, x0, y0, x1, y1, collision=WALL_COLLISION)
      # Outside the map: wall on the back layer, nothing on the others.
      patterns: list[list[int | None]] = [[None] * (BORDER_SIZE * BORDER_SIZE) for _ in maps.layers_of(doc.data)]
      patterns[BACK_LAYER] = [wall] * (BORDER_SIZE * BORDER_SIZE)
      maps.set_border(doc, BORDER_SIZE, BORDER_SIZE, patterns)
   with world.world.edit("Start position"):
      world.world.data["start"] = {"map": START_MAP, "x": sx, "y": sy, "facing": START_FACING}
   return width, height


def fill(world: Project) -> list[str]:
   """!Adds the starter tileset and map to a world that has neither, and starts the world on the map (unsaved;
   Project.save_all() writes them).
   @param world  the world (new, or with no tileset "basic" and no map "start")
   @return report lines
   @throws DocumentError when the world has a tileset or map of those names already
   """
   if TILESET in world.tileset_names() or START_MAP in world.map_names():
      raise DocumentError(f"the world has a tileset {TILESET!r} or a map {START_MAP!r} already")
   _add_tileset(world)
   width, height = _add_map(world)
   sx, sy = start_position()
   return [f"tileset {TILESET}: {len(METATILES)} simple-shape metatiles ({', '.join(METATILES)})",
           f"map {START_MAP}: {width} x {height}, start at {sx},{sy} facing {START_FACING}"]
