# CapsuleCreatures editors

The **Studio** (`./studio`) hosts every editor in one window, on one game.
Each editor also runs by itself, from its own launcher:

- the **scene editor** (`./scene-editor`) edits asset manifests
  (`capsule.assets/1`): sprite frame animations, text and credits, text
  boxes and menus, screen graphics and screen plans;
- the **map editor** (`./map-editor`) edits worlds (`capsule.world/1`) with
  their tilesets and maps: the Map and Tileset tabs, with the map tools and
  overlays of the world tools below;
- the world tools, each an extension (see Extensions) on the same
  world.json, each a tab of the Studio's World page:
  - the **encounter editor** (`./encounter-editor`): encounter tables
    (`capsule.encounters/1`);
  - the **event editor** (`./event-editor`): warps, triggers, signs and
    step hooks;
  - the **object editor** (`./object-editor`): characters, spotters and pickups;
  - the **location editor** (`./location-editor`): locations, name banners,
    previews and the world's warp transition;
- the **battle editor** (`./battle-editor`; `./battle-structure` and
  `./battle-logic` open it on those pages) edits battle data
  (`capsule.battle/1`), its ruleset (`capsule.ruleset/2`) and the structure
  manifest and effect sources it names;
- the **script editor** (`./script-editor`) edits a game's scripts
  manifest (`capsule.scripts/1`) and its `.cscript` sources: scripts, flags
  and variables;
- the **project settings** window (`./project-settings`) edits a game's
  project manifest (`reference/project.json`, `capsule.project/1`): its
  build settings and code page, and a build folder's GBA memory settings.

Every editor is written as panels a host window shows (`ui/panel.py`), so
the standalone windows and the Studio are the same code.

## Scene editor

What it does so far:

- **Animation**: add frames, set how long each frame shows, import frame
  bitmaps (PNG, BMP, GIF, JPEG and anything else Qt reads), reorder,
  duplicate, remove, loop or hold, several animations per sprite. I3: a
  step may be drawn **mirrored** (the Mirrored column), a sprite may be
  **streamed** (only the shown frame in VRAM, so its frames may use more
  tiles than a slot holds) and have a **step table** (the walk animations'
  standing and starting entries), **Indexed sheet...** adds every frame of
  a palette PNG of frames, its indices used as they are, and **Half speed**
  previews the engine's half-speed playback. Playback
  runs at the GBA's frame rate in the colors the GBA will show, next to the
  palette and the sprite's tile use against its 64-tile slot.
- **Text**: text assets, checked against the game's code page (its
  `reference/project.json` `"text"` object; the engine's ASCII page when it
  names none) and screen width, previewed in the game's font in a text box
  or on a layer. Any Unicode text can be typed; characters the page neither
  maps nor aliases are underlined (give them a code on the Project page's
  Code page tab).
- **Credits**: pages of a heading and names, previewed the way the credits
  sequence shows them, importable from and exportable to a plain text file.
- **Fonts** and **Text boxes** [S6b] (engine C13a / C13c): a font's
  **Glyph height** is the rows of each glyph a text window draws ("whole
  cell" when 0): rows below it, and columns past a glyph's width, stay in
  the font but never show, so the editor draws them darker and marks the
  glyph height with a line. Previews draw as the engine's window does,
  controls included: Fill, Clear, SkipTo, ClearTo, MinSpacing, and
  ShiftRight / ShiftDown counted from the text's start. A text box style
  says how many tiles and bytes its window needs from the game (a
  `TileBuffer<W, H>`, given with `window::attach()`).
- **Screen graphics** [S6] (engine UC): the tiles, tilemaps and palettes a
  full-screen scene loads where its own plan says. New tiles (a canvas to
  draw shapes on), tilemaps (cells of tile 0) and palettes (gray ramps);
  **Import PNG...** turns an indexed PNG into a tiles file beside the
  manifest (identical and flipped tiles shared, a palette bank per tile), a
  tilemap laid out as a layer's map memory holds it and a palette of whole
  banks, or into sprite frames (tiles in reading order). A tilemap is
  painted by clicking its preview (tile, bank, flips, a rectangle and a tile
  step for runs; click the tiles strip to pick a tile); a palette's colours
  by clicking a swatch (type `#rrggbb` or pick one). **Export PNG...** writes
  tiles as an indexed PNG for a paint program.
- **Screen plans** [S6] (engine UC): a screen's layers (the layer templates,
  what each loads, scroll, templates applied later with `layers::init()`),
  palettes, text windows, sprite sheets (loaded or reserved tiles), sprites,
  frame steps and open / in / out transitions, as a plan file
  (`screens/NAME.screen.json`, beside the manifest). The preview simulates
  the GBA's video memory, so a map written over tiles shows as the hardware
  would show it, and plays a transition call by call as the engine's fade
  steps it; Problems lists what would go wrong (memory clashes, layers the
  display mode has not, colour modes, sheets and banks that do not fit),
  Video memory where everything goes. **Export C++...** writes the plan's
  tables (`layers::Plan`, `screen::Step`, `screen::Transition`, window and
  sprite places, tags) as a header for the screen's code. S6b (engine C13a /
  C13c): each window shows the tiles and bytes of the buffer the screen gives
  it (exported as a `TileBuffer` type), the plan its total; **Exit** says how
  the screen leaves: `close()` (its out fade, then it leaves the frame after
  the last call), `close_now()` (it faded itself: it leaves at the end of the
  frame), `replace()` / `replace_now()` (the same, then the **next** screen),
  with the frames on the **Exit timing** tab and a `leave()` in the export.

Everything is validated with the engine's own asset compiler as you edit,
so what the editor accepts is what the build accepts.

## Run it

From the repository root:

```
./scene-editor [path/to/assets.json]        # Windows: scene-editor.cmd
```

It runs in the toolkit environment (`.venv/` in the toolkit's folder, see
the toolkit README): the installers set it up, and if they haven't, the first
launch does, installing the pinned PySide6 into it. Nothing is installed
system-wide.

`--panel animation`, `--panel text` or `--panel credits` opens one editor on
its own.

Every editor window has **Open**, **Save**, **Undo** and **Redo** buttons
under the menu bar, plus **Save all** in the map and battle editors, which
edit several files, and **Import** in the map editor. They do the same as
the File and Edit menu items and their shortcuts (Ctrl+O, Ctrl+S,
Ctrl+Shift+S for Save all, Ctrl+Z, Ctrl+Y / Ctrl+Shift+Z). Undo and
Redo name the change they act on ("Undo Paint") and work on the file the
current tab edits. In the map editor, Save writes the map or tileset you are
editing, and the world file too when it changed (a new map is listed there);
Save all writes every changed file.

The editor needs a capsule-engine checkout for the compiler, the font and
the VRAM limits. It looks in `$CAPSULE_ENGINE`, then `../engine` (the
engine submodule beside this toolkit in the `CapsuleCreatures` umbrella;
in a prebuilt Studio download, the engine copy it ships), then
`../CapsuleCreatures_Engine` (a standalone engine clone beside a standalone
toolkit clone).

## Studio

```
./studio [path/to/reference/project.json] [--page world|assets|scripts|battle|project|audio]
                                            # Windows: studio.cmd
```

The Studio opens a game through its project manifest: each file the
manifest names (`maps`, `assets`, `scripts`, `battle`, `audio`, relative to the game
folder; `capsule-studio project files` lists them) opens on its page, and
the manifest itself on the Project page:

- **World**: the map editor's Map and Tileset tabs and the world tools'
  tabs (Encounters, Events, Locations, Objects, and the panels of the
  game's plugins), which follow the map chosen in the Map tab;
- **Assets**: the scene editor; **Scripts**: the script editor;
  **Battle**: the battle editor; **Project**: the project settings;
  **Audio**: the audio editor, on the manifest the project names under
  `audio`.

The page list on the left marks a page with unsaved changes (`*`); its
tooltip names the file the page has open. Ctrl+1 to Ctrl+6 go to a page.
The menu bar holds the **Studio** menu (Open project..., the pages, Quit),
the menus of the page in front, whose toolbar and status bar stay on the
page, and **Help** (Record performance records the whole Studio). Only the
page in front has keyboard shortcuts, so Ctrl+S saves what you are looking
at.

Opening a game checks that each file opened; a page whose file the project
does not name, or whose file did not open (an error, or a conversion you
declined), starts empty when you show it, and a message lists what did not
open, so no page keeps the previous game's file. The Project page's Open
project... opens a whole game, like Studio > Open project...; the other
pages' File menus still open another file on that page alone (another
world, say). Closing the Studio, or opening another game, asks each page
with unsaved changes about them, showing that page first.

Pages keep their own documents: what you change on one page reaches the
others once it is saved (a flag declared on the Scripts page shows in the
Objects tab's choices after Save). Edit a world in one window at a time:
the map editor and a standalone world tool opened on the same world do not
see each other's unsaved changes, and the one that saves last overwrites
the maps the other changed. The Studio's World page holds the map and the
world tools in one window, so they share the same documents.

Started without a project, it opens a small start window (Open project...,
New game..., Open a sample..., recent projects, Continue without a project).

**Open a sample...** (Studio menu and start window; D-40 RP) copies one of
the engine's sample projects, the apps with a `sample.json` (Starter Battle,
Map Sandbox; `core/samples.py`), into a new (or empty) folder as a game of
its own and opens it: on the World page when it has a world, else on the
Battle page. The copy gets the app's files and its own copy of the engine
data the app shares (the Starter's template files in `data/starter`, with
every manifest path pointed at them), New game's build-safe `"name"` and
ROM header, and `editor.sample {id, version}`; it is refused inside the
engine or the Studio's own folder, and `capsule-studio sample check`
confirms nothing in it leads out of its folder.

**New game...** (Studio menu and start window) makes a game from a battle
data template and opens it: pick a template, see what it gives and its
files by part (structure, logic, content), name the new (or empty) folder
and the game. The game gets the template's files in `data/` with their
relative paths (`effects/` stays `effects/`) and a `reference/project.json`
naming its `battle` and `assets` manifests. Templates come from the studio
(**Blank**: neutral, minimal battle data that compiles: hit points, Power,
Guard and Speed, physical and support moves, one type and one trait, no
condition records and no logic), the engine's samples (**Starter**, the
engine's `samples/starter`: nine stats with HP, MP and EP pools, effect
odds by Intelligence, nine types, creatures, rivals and shape art), the
reference rules' `templates/` (a private reference-ruleset repository, not
part of this release, named by `CAPSULE_REFERENCE`)
and plugins (`ctx.add_battle_template()`). Every JSON manifest copied
records the template it came from (`editor.template {id, version}`, which
the compilers ignore), so a newer template version can be compared later.
The battle editor's **New battle data...** opens the same dialog for battle
data alone, into any folder, with only the parts you tick. Nothing is
overwritten.

**Add world to game...** (Studio menu, and the World page's File menu in the
Studio) names a world in the open game's `reference/project.json`
(`core/game_world.py`): the engine's map sandbox world (Map sandbox) or a
chosen `world.json`. A world inside the game folder is named as it is; one
outside it is imported first (the import dialog, every map ticked) into the
game's own world, which is `data/world.json` when the game has none
(`data/world_2.json`, ... when that name holds something else). A world
that names no battle data, or battle data outside the game, then uses the
game's `battle` file. The world files are saved, then the manifest (through
the manifest writer), and the game opens again on its World page.

## Map editor

```
./map-editor path/to/world.json             # Windows: map-editor.cmd
```

If an editor feels slow, use **Help > Record performance**: work as usual,
then uncheck it. A report goes to `profiles/` (display setup, every pause
over 50 ms and what you did just before it, and where the time went).

Started without a world, it opens a small start window: **Open world...**,
**New world...**, the worlds opened recently and **Continue without a
world**, which opens the editor with nothing loaded (File > Open world... or
New world... loads one later). The editor window (with the map and tileset
tabs) opens once a world is open; closing the start window quits.

The map editor shows the Map and Tileset tabs. The world tools' map tools
(Encounters, Events, Objects) and overlays are in its Map tab too; their
panels are in their own editors and on the Studio's World page. In the map
editor, the Events and Objects tools place and remove; moving needs an
event or object chosen in its tab, so it moves only the one you placed
last (the Studio's World page has the tabs).

- **Map** tab, laid out like common tile-map editors: the map list fills the left side,
  the map in the middle, and on the right the layers, the border and then
  the palette of the map's tilesets. The map list shows the world's map
  groups as folders (stored in world.json as `map_groups`; maps in no group
  come last); filter it by name, drag a map or a group onto a group (or
  between items) to reorganise, and right click for New map / New group /
  Rename / Remove group (its maps move up) / Take out of the group. **New
  map...** and **New group...** under the list put the new one in the group
  chosen in the list. Undo right after a group change takes it back.
  A map has up to four tile layers, each on
  its own GBA background (BG0-BG3) with its own draw priority, and an
  attribute layer. **Layers** on the right lists the attribute layer, then
  the tile layers front to back: click one to paint on it, untick it to hide
  it (unticking Attributes hides the attribute overlay). Below the list, a
  tile layer's background, priority (0 is in front; on a tie the lower BG
  is) and purpose are changed, and **Add layer** / **Remove layer** add one
  on a free background or remove one with what is painted on it. New maps
  get BG3, BG2 and BG1 (the text layer uses BG0).
  **Tilesets...** chooses the tilesets a map draws from; the palette shows
  every metatile of those as pictures on a grid (the name is the tooltip;
  arrow keys move the choice; drag across the palette, or shift-click, to
  pick several metatiles at once). On a tile layer: paint, drag rectangles,
  flood-fill, **Clear** (removes that layer's metatile; the cell stays
  painted), **Erase** (unpaints the cell on every layer: the border shows
  and it is always blocked); right click picks the layer's metatile, and a
  right-drag picks a rectangle of them from the map. Several picked
  metatiles paint together as a stamp (shown see-through under the mouse);
  dragging, rectangles and fills repeat it from where they start, so the
  pattern lines up.
  **Fade layers in front** draws the layers in front of the current one
  see-through. **Zoom** (lower right of the map) goes from 50% to 600%
  (100% is one screen pixel per map pixel) and keeps the middle of the view
  in place; the grid shows from 100% up. On the attribute layer, choose the attribute (collision 0-3,
  elevation 0-15, behavior, encounter, environment tag 0-255) and its value,
  then paint, drag rectangles or fill it onto painted cells; the overlay
  shows the chosen attribute and right click picks its value. Painting a
  metatile on an unpainted cell gives it default attributes (the world's
  first behavior, everything else 0). Painting outside the chunks adds
  chunks. The map's metatile and behavior lists in the file follow what is
  painted (nothing to import or clean up). On the right, the border (the
  pattern repeated outside the map, one per tile layer) is painted the same
  way on the current tile layer: drag with Paint, Fill sets every cell,
  Clear or Erase empties cells, right click picks; its size, the backdrop
  color and removing empty chunks are below it. **New map...** asks for a
  name and its tilesets and starts blank. A drag is one undo step.
- **Tileset** tab: the world's tilesets. New tilesets start empty. Import
  sheet images (PNG, BMP, GIF, JPEG; their colors become the sheet's
  palette, up to 15; **Transparent color** under the sheet makes one color
  of the source image transparent: **Pick from sheet** and click it, or
  **Choose...**), make one metatile per non-empty 16x16 block with
  **Metatiles from sheet blocks**, or compose metatiles in the metatile
  maker, a 2x2 map of 8x8 tiles: pick a tile on the sheet (or drag across
  up to 2x2 tiles) and drag it out onto the maker, where it lands with its
  top-left tile under the mouse; dropping on the metatile list makes a new
  metatile, and so does dropping on the maker when no metatile is chosen.
  In the maker, click or drag stamps the picked tiles, right click clears,
  H / V mirror the tile under the mouse; Flip H / Flip V place the picked
  tiles mirrored (a 2x2 block as a whole). **New** adds a blank metatile. Metatiles are graphics only: behavior, collision and the
  rest are painted on the map's attribute layer, so one metatile can be
  used on any layer. Renaming a metatile renames it in every map using it.

**Import** (File > Import from another world...) brings maps and tilesets
from another world into the open one: pick its world.json, tick maps and
tilesets, and the dialog shows what comes along before you confirm. A map
brings the tilesets it draws from, their sheet images and the behaviors its
cells use (with the vehicle classes those name). A tileset identical to one
already here is reused; a different one of the same name, or a clashing map
name, is imported as name_2 and the imported maps follow it. A behavior the
world already has keeps this world's definition, and world settings (start,
elevation priorities) stay as they are. An imported map goes into a group
of the same path as in the other world (created when missing). Both worlds use the same manifest
formats for now. The imported files are unsaved until Save all.

Everything is checked by the engine's map compiler as you edit (limits:
1,024 tiles, 13 palettes, 32 tile animations and 4,095 dictionary entries
per map). Save writes the map or tileset you are editing, Save all every
changed file; new sheet images go to `sheets/` next to their tileset.

### Imported worlds: fixed tilesets and "all" dictionaries (engine I2)

- A **fixed-placement tileset** (`"place"`) holds imported indexed graphics
  as they are: its indexed sheets (palette PNGs used as their indices) load
  at a fixed VRAM tile, its palette banks (`"palettes"`, 16 colors each) at
  a fixed bank, and its metatiles are raw tilemap entries (VRAM tile, mirrors
  and bank) that may name tiles another fixed tileset of the map places. The
  Tileset tab's **Fixed placement** tab edits the placement (sheet, first
  tile, tiles owned, first bank, banks owned), the banks (click a color) and
  the chosen metatile's four entries; **Bank** under the sheet picks the
  bank the sheet is shown in and new entries take, and picking tiles of the
  placement sheet into the maker makes entries. **Make fixed placement**
  turns an empty tileset into one, **Import indexed sheet...** adds a
  sheet (copied next to the tileset). A fixed tileset's pictures are drawn
  with the tilesets maps load together with it ("Pictures drawn with").
- A map's dictionary may be **every metatile of its tilesets**
  (`"metatiles": "all"`, as imported maps are: their cells are the
  tilesets' metatile numbers). The Map tab's **Dictionary: every metatile
  of the tilesets** box switches between that and the metatiles painted;
  the cells are renumbered so they show the same. Choosing other tilesets,
  or adding, removing or reordering a tileset's metatiles, renumbers the
  "all" maps that draw from it in the same undo step (a removal of a
  metatile such a map paints is refused).
- **Animations** (the Tileset tab's Animations tab, any tileset): the first
  tile (`"sheet:index"`, or for a fixed tileset its number counted from the
  placement's), tiles, frame sheet, period, **phase** (frames into the
  period at map entry; auto: the compiler spreads them), **start from the
  sheet's own tiles** (I3 `from_sheet`) and what a seamless map shift does
  (I3 `on_shift`: keep, reload, restart).
- **Large worlds** (an imported world of hundreds of maps and dozens of
  fixed tilesets) open in a few seconds: a map compiles against its own tilesets
  (each compiled once per change), the event check runs again only when an
  event, object or the cells they stand on changed. A world of more than
  64 maps is not compiled whole when it opens; World > Validate compiles it
  in the background (about 15 s for 500 maps; the editor is slower meanwhile)
  and the status bar shows its result.

### World settings: behaviors and movement modes

- **Behaviors** tab: the world's terrain classes: solid, the movement modes
  that enter it, what it does (slide, ledge, push, or I3's **counter**: A
  facing it talks to the object beyond) and, I2, its **walls**: the sides
  a step may not cross, leaving or entering (one-way fences). **Add...**
  adds one.
- **Movement modes** tab (I3): a mode's **turn in place** time (frames;
  default the field's), **bumps** (a blocked step walks in place) and
  **keeps moving** (arriving with another direction held steps on without
  turning first).
- **Interactions** tab [S6b] (engine C13b): what Accept does facing a cell
  when no object or sign answers: rules tried top to bottom (**Up** /
  **Down**), each a behavior of the cell faced and the script it runs, with
  optional conditions: the direction faced, the movement mode, a flag that
  must be set, the faced cell on the player's level, or only after the field
  actions had nothing to do. The engine's map compiler checks every change;
  below the form, what the build refuses (with the scripts' names) and rules
  an earlier one always takes.

## Map events

Warps, triggers and signs (design B-3) are an extension: the **event
editor** (`./event-editor path/to/world.json`, Windows: `event-editor.cmd`)
shows its **Events** panel on its own, with a map chooser; on the Studio's
World page it is the **Events** tab and follows the map chosen in the Map
tab. The map editor keeps the Events map tool and the Map events overlay.

- **Events**: the map's warps, triggers and signs with their cells. The
  form edits the chosen one: its cell and level (any level, or 1-15), and
  - a **warp**: the map and warp number it lands on (I3: or **dynamic**:
    the game decides when it fires, e.g. the exit of a shared interior), what
    fires it: arriving on the cell (step), pressing a direction while
    standing on it (press), the same while already facing that way (I3
    **arrow**), pressing it facing the warp from the cell before it (I3
    **door**: the game opens the door) or nothing (I3 **none**: a landing
    other warps name, kept so warp numbers stay the source's), and its
    **transition** (see Warp transitions below);
  - a **trigger**: the script it runs when the walker arrives, optionally
    only while a variable holds a value;
  - a **sign**: the script it runs when the player presses A facing it, the
    facing it needs, and a flag that hides it once set (hidden items).
  Scripts, flags and variables are offered from the world's scripts
  manifest. Removing a warp renumbers the warps after it, and every warp of
  the world that lands on one of them follows; a warp others land on is
  refused until they point elsewhere.
- **Area**: the outdoor map whose area this map is in (B-2: leaving an area
  clears its area flags and variables); outdoor maps are their own area.
- **World**: the scripts manifest (the game's project.json must name the
  same file) and the step hooks (game code that runs every period-th step;
  powers of two).
- **Events on unpainted cells** (I3 `unpainted_events`): the map's
  events and objects may stand on unpainted cells, and warps land on them
  (imported data kept as its source has it).
- **Problems**: what the build would reject (from the engine's compiler),
  warps or triggers on cells with collision, and doors opened from a cell
  the walker cannot stand on.

In the Map tab the extension adds the **Events** tool (click a cell to
place a new warp, trigger or sign, to move the event the Events tab shows
there, or to remove the events on it), the **Map events** overlay (W, T and
S on the cells that have them; I3: D a door, A an arrow, L a landing only,
? after a dynamic warp) and the hovered cell's events in the status line.

## Map objects

Characters, spotters and pickups (design B-21, D-17) are an extension: the
**object editor** (`./object-editor path/to/world.json`, Windows:
`object-editor.cmd`) shows its **Objects** panel on its own, with a map
chooser; on the Studio's World page it is the **Objects** tab, after Events
and Locations, and follows the map chosen in the Map tab. The map editor
keeps the Objects map tool and overlay.

- **Objects**: the map's objects by local ID (at most 15 per map: sprite
  slots 1-15; I3: up to 64 with an **Object view**, the cells left, right,
  above and below the player its objects spawn in). **Stacked objects**
  (I3) lets objects share a cell (data whose flags keep one there at a
  time). Scripts address objects by local ID (`world_ids.h`
  `OBJ_<MAP>_<NAME>`), `self` or `player`, so removing an object moves the
  local IDs after it down by one; the tab and the command say which.
- The form edits the chosen one: its name, cell and level, its sprite
  (offered from the game's assets), facing, movement (static, look_around,
  wander, pace_vertical, pace_horizontal, approach, custom; I3: the
  reference games' turn, roam, rotate, patrol, circuit, mirror, in_place and
  invisible; wander, the pace types, roam, patrol, circuit and mirror with a
  range box up to 15 cells, custom with a move route) and its **Settings**
  (I3 `movement_args`, the widgets the movement takes: a turn's or roam's
  2 or 4 choices and delays, turning to a running player, a rotation's
  direction, a circuit's four legs, a mirror's reference facing and the
  vehicle class whose terrain it keeps to, an in_place's pace, a static
  object keeping a facing a script gave it), speed (1-4) and
  frequency (1-5), movement options, the script and its trigger, the flag
  that hides it while set, its self switches, and, for a spotter (an object
  that watches the cells in front of it: `"spotter": {"sight", "until"}`),
  its sight (1-8 cells) and the flag that ends its watch. Fields that mean
  nothing with the others are dropped (a range without a moving type, a
  route without custom movement, an until flag without sight), and so are
  values that are the defaults.
- **Pages** (RPG Maker XP's event pages, D-17): each page waits for
  conditions (a flag set, a variable at least or equal to a value, self
  switches A-D on; at least one) and replaces some of the object's fields:
  sprite, movement, range, route, speed, frequency, options, facing,
  script, trigger; or makes the object absent. The last page whose
  conditions all hold is the active one; with none, the object's own fields
  are. Pages are chosen again whenever a flag, variable or self switch
  changes. Up and Down reorder them (later pages win). Worlds from before
  D-17 had "overrides" (the first whose flag was set applied); importing
  such maps turns each override `{flag, ...}` into a page `{"when": {flag},
  ...}`, in reverse order, so the same one wins.
- **Problems**: what the build would reject (from the engine's compiler),
  objects on cells with collision, sprites the game's assets lack (the
  object would be invisible but solid) and objects standing on warps.

In the Map tab the extension adds the **Objects** tool (click a cell to
place a new object, to move the object the Objects tab shows there, or to
remove the objects on it), the **Map objects** overlay (O for an object, S
for a spotter, with its facing as v ^ < >, and the spotter's sight line)
and the hovered cell's objects in the status line. Importing maps between
worlds keeps their objects, except those naming scripts, flags or variables
the world lacks, in their pages and routes too (reported).

### Triggers, movement options and move routes

- **Trigger** (what starts the object's script): `action` (the player
  faces it and presses A; the default), `player_touch` (the player walks
  into it), `event_touch` (it walks into the player, or the player into
  it), `autorun` (runs again and again while its page is active; the
  player waits) and `parallel` (runs alongside play). Autorun and parallel
  objects need a script.
- **Options**: walk anim (on by default), step anim, fixed facing
  (`direction_fix`), through and on top. A page with its own options starts
  from these defaults, not from the object's.
- **Self switches** A-D: four permanent bits per object, given to objects
  whose pages test them or whose scripts use them, or when the form's check
  box asks for them.
- **Move route** (movement custom): typed into the route box, one step per
  line, and checked with the engine's `tools/route_compiler.py` as it is
  typed (Apply stores it as one undo step): `up` / `down` / `left` /
  `right [n]`, `random`, `toward`, `away`, `forward`, `backward`,
  `jump dx dy`, `wait n`, `face X`, `turn right | left | around | random`,
  `set FLAG` / `clear FLAG`, `speed n`, `frequency n`, `walk_anim` /
  `step_anim` / `direction_fix` / `through` / `on_top` `on | off`,
  `sprite sprite:NAME`, `show`, `hide`. **Repeat** (on by default) starts
  over at the end (such a route needs a step that takes time); **skip
  blocked** skips a step that is blocked instead of waiting. A route makes
  the movement custom; choosing custom without one starts with a short
  look-around route. Pages can give their own route (their movement
  becomes custom).

## Locations, banners and previews

Locations (D-17) are an extension: the **location editor**
(`./location-editor path/to/world.json`, Windows: `location-editor.cmd`)
shows its **Locations** panel on its own; on the Studio's World page it is
the **Locations** tab:

- **World**: the default warp **transition** (warps that name none use
  it; fade unless set).
- **Banner styles**: a plain box in its colors (ink, shadow, fill,
  border), or a 24x24 **frame** PNG (3x3 tiles: corners, edges, interior)
  whose pixels in the fill color become the text background; how many
  frames the banner stays and how many it takes to slide in.
- **Locations**: the named places maps belong to: the banner's text (at
  most 28 characters, in the font), its style (none: no banner), and the
  **preview**: a sequence (capsule.sequence/1) played full screen while the
  map is hidden when the player enters the location, every time
  (`always`) or on the first visit (`first`). A preview lists up to 8
  sequences; the last whose conditions (the world's encounter conditions:
  time of day, ...) all hold plays, so morning / day / evening / night
  previews are four entries. Renaming a location changes the maps naming
  it; removing one leaves them in none.
- **Map**: the location of a map (on the Studio's World page, the map
  chosen in the Map tab: it follows it).
  A banner slides in when the player enters a map whose location differs
  from the last one's.
- **Problems**: what the build would reject (from the engine's
  `tools/location_compiler.py`), locations no map is in, and maps in no
  location.

The hovered cell's location shows in the status line. Importing maps
brings the locations they name, with the banner styles they use and the
encounter conditions their previews wait for; a location or style the
world has keeps the world's definition, and frames and sequences stay where
they are (the copies refer to the source's files).

## Warp transitions

A warp's **transition** (D-17) is how the screen changes when it fires:
`none`, `fade`, `white` (fade through white), `mosaic`, `wipe_h`, `wipe_v`
or `box`. The Events tab's Transition chooser sets it per warp; "(world
default)" leaves it out, so the world's transition (the Locations tab)
applies.

## Encounter editor

```
./encounter-editor path/to/world.json       # Windows: encounter-editor.cmd
```

Encounters (design D-12) belong to a world: the encounter editor opens
the same world.json as the map editor and shows one panel, **Encounters**;
the Studio's World page shows that panel as a tab, following the map chosen
in the Map tab. The map editor keeps the Encounters tool and the Encounter
tables overlay.

- **Encounter files**: each map's tables (in `encounters/<map>.json`,
  created on the first table) and the world's **shared tables**
  (`encounters/shared.json`), which maps use by name.
- **Tables**: a map assigns its encounter cells to **slots** (0-15) and
  has one table per slot and **method**. A table has a rate (the odds a
  step, or a script roll, starts an encounter: `1/10`, `12.5%`) and
  weighted entries, or uses a shared table (Use shared..., or Copy shared
  here to edit a copy).
- **Entries**: species (from the world's battle data), levels (`5` or
  `3-5`), weight, the conditions they require or exclude, and modifiers
  (`rain x0, night x2`). The Share column shows how often each entry comes
  up under the conditions ticked under Preview with, computed exactly as
  the engine rolls (integer weights, truncating multipliers).
- **World**: the battle data species come from, the methods (rolled by
  steps for some vehicle classes, like walking and surfing, or by game code,
  like each fishing lure) and the condition names (bits game code sets: time
  of day, weather, swarms). Renames follow every table; removing something a
  table uses is refused.
- **Problems**: encounter cells in a slot without a step table (nothing
  rolls there), tables without cells, empty tables, unused shared tables,
  and the compiler's message.

In the Map tab the extension adds:

- the **Encounters** tool: paints encounter cells in a slot (or takes
  encounters off) on painted cells; drag for a line, shift-drag for a
  rectangle; its slot chooser shows under the toolbar;
- the **Encounter tables** overlay (Overlay chooser): encounter cells
  coloured by slot with the slot number, red where the slot has no step
  table;
- the hovered encounter cell's tables in the status line, and its problems
  under the map.

The attribute layer also has the **Encounter slot** attribute (paint,
fill, pick and overlay like the other attributes).

## Battle editor

```
./battle-editor path/to/battle.json         # Windows: battle-editor.cmd
./battle-structure path/to/battle.json      # the same window, Structure pages first
./battle-logic path/to/battle.json          # the same window, Logic pages first
```

Started without a file, it opens a small start window (open, new, recent,
or continue without battle data), like the map editor.

A navigator on the left groups the pages: **Content** (Species, Moves,
Types, Parties, Presenters, Passives / Items, Data), **Structure** (Record,
Stats & Stages, Resources, Passive slots, Categories, Type chart, Flags &
Tags, Conditions, Formats & Turn, Progression, Terms, Text) and **Logic** (Effects, Formulas, Pipelines
& Points, Bench). Pages not built yet say what they will edit, which work
package builds them and where that data is edited meanwhile; they edit
nothing. Page titles use the game's words. The Studio's Battle page is the
same window with the same navigator. `--group content|structure|logic`
picks the group in front, `--panel ID` opens one page alone.

Besides its ruleset, battle data may name a structure manifest
(`"structure": "structure.json"`, `capsule.structure/1`) and effect
sources (`"effects": ["effects/moves.ceffect", ...]`). The editor opens them
with the battle data, each file with its own Undo history, and saves them
with it; a named file that does not exist yet starts empty and is written
by the next save. The engine's compiler reads the effect sources, unsaved
edits included (it does not read the structure manifest yet). An edit of the
battle file that also rewrites effect sources (a rename that follows the
logic) is one Undo step, from either file: undoing it undoes the edits of
both, except in a source changed after it.

- **Species**: types, base stats (one per stat of the battle's `"stats"`,
  labelled by each stat's abbreviation or label), passives (one per passive slot of the structure),
  growth, experience yield, sprite keys, the learnset, and the stats the
  engine's formulas give at a chosen level and gene value.
- **Moves**: type, category (its type's under category_by_type), power,
  accuracy (or never misses), the base of each move resource and the cost in
  each resource (D-25), priority, target, flags and critical stage. What a move does is its block
  in the effect sources (`move "Fireball" { hit { ... } }`), edited under Logic >
  Effects or with `battle FILE effect ...`; a damaging move without one hits
  once per target.
- **Types**: the type list and the chart; click a cell to step its
  multiplier (1, 2, ½, 0, 4, ¼, KO), right click to step back.
- **Parties**: reward base, rank, whether the player may escape, AI flags,
  the presenters shown for the party (add, remove, reorder: the first enters
  first; at most two), the members (species, level, item, passive slot (by name),
  genes, trait, moves or the learnset's) and what the intro shows. A member
  has one move box per move slot of the record layout, a party at most the
  layout's party size, and genes go up to what the layout's `stat_genes`
  width holds (the Species preview and the damage calculator too; training
  follows `stat_training`).
- **Passive slots** (Structure): the structure's `"passive_slots"` (D-25,
  engine C1), the slots a species fills with its passives, in slot order:
  name (typing renames it; members naming it follow), Rolled (the generation
  list's passive_selector entry may roll it; an unrolled slot is one only
  data or logic gives, such as a hidden passive) and how many species and
  members use it. Add / Remove / Rename / Up / Down are one Undo step with
  the species' passives (a removed slot's place goes from every species), the
  members' slots (a member having a removed slot falls back to the first) and
  the saved bench scenarios' members. The budget line shows the slots against
  the engine's most on every target ("2/4 passive slots (gba)") and the
  record's passive_selector role, which must hold the last slot's number. A
  structure without the list has the engine's default (one rolled slot).
- **Record** (Structure): the creature record (`"monster_layout"`) role by
  role, in order. Engine roles are grey with their fixed IDs; the width of
  some is editable up to the engine's maximum, per-stat roles hold one
  element per stat and move roles one per move slot. Custom roles (name,
  width, count, default; a field the engine stores and scripts read and
  write) get the ID 0x80 + their place among the custom roles. Drag a row
  (or Up / Down) to reorder; add engine roles from the list, custom roles
  with the form. Party size and move slots switch the layout to its object
  form (`{"party_size", "move_slots", "roles"}`). A bar per target platform
  shows the record's bytes ("60/100 B GBA"), red when over; the layout hash
  and size come from the engine's own `compile_layout()`, with a warning
  when the hash differs from the saved file's (old saves won't load). The
  transfer keys column shows what a record transfer finds each role by:
  engine roles by their ID, per-stat roles by the stats' transfer keys,
  custom roles by `role:` + their name (the 32-bit key in the tooltip).
- **Presenters** (who shows a party on screen and speaks for it): the
  sprite (from the game's sprite assets, or none: text only), the offset
  from where the side stands, the entrance and exit (none, slide from / to
  an edge, fade, a sequence file; an exit may also stay, and leaves at the
  first send-out or right after the intro), whether it comes back at the
  end, and its intro / defeat / victory texts. Texts take `{party}` and
  `{@concept}` terms; each is checked as it is typed (unknown placeholders
  and terms, characters the game's code page lacks) and shown as it reads.
  The preview draws the format's screen (battler places, the sides' stands)
  and plays the entrance, exit or return frame by frame exactly as the
  engine's presenter_view does (`battle FILE presenter-track`). The studio
  has no sequence editor yet: a sequence is a JSON file picked with Choose...
- **Text** (Structure): the game's language, its code page and the
  characters its saved texts use that the page lacks; **Open the code page**
  opens the project's Code page panel (the Studio's Project page, or the
  project settings window).
- **Terms** (Structure): the game's word and plural for every concept; the engine's
  defaults (and plurals the compiler derives, the word + s) are greyed;
  Reset puts the selected concepts back. Page titles and labels across the
  battle editor use these words (a game that calls parties "Trainer" gets a
  Trainers page).
- **Stats & Stages** (Structure): the battle's stats in record order (name,
  label, abbreviation, formula from the ruleset's stat formulas, the pool /
  order / odds / stage / trait flags (at most one odds stat: the effect_odds
  pipeline reads it for both battlers), transfer key, stage number), with
  Add, Remove,
  Rename and Up / Down (each one Undo step, every species' base values
  following). Renaming follows the categories, traits and the effect logic
  that reads the stat or its stage, and
  a stat without its own transfer key keeps its old name as the key, so
  creatures moved between games still match. A new stat can't take a name
  another stat uses as its transfer key, and a transfer key must be no other
  stat's (both refused at once). The budget line shows the stat
  count against each target platform of the game (its project.json
  `"targets"`, e.g. "6/10 GBA"), red when over. Below: every stage in engine
  order with the fixed stages' in-game names (editable), and a preview of the
  stage multipliers and critical-hit odds of the rules.
- **Effects** (Logic): the effect logic of every move, passive, item,
  status, weather, volatile and side / field condition, kept in the battle's
  `.ceffect` sources. The owner tree
  groups the owners by kind or by source file and filters them by "has
  logic" (off: every entry, the ones without logic grey; Add logic gives one
  an empty block) and by the hook, phase or point they use; Remove logic and
  Give to... (the logic of another entry of the kind). The owner's handlers
  sit next to a hook / point picker that shows what the engine's catalog
  says about the choice (who `holder` / `other` are, the value and its range,
  the verdicts, the engine's own random draws, whether the handler may yield,
  per_foe) and a budget meter of the selected handler (VM stack, worst-case
  events, whether it draws; measured by the engine's effect compiler). The
  Block view and the Text view show the same logic. Blocks: drag a statement
  (or Up / Down), Delete, insert from the palette (Control, Values, Actions,
  Results, Presentation) and edit the selected statement's fields;
  expressions complete words and show their analysed range, the read
  picker builds `holder.stat(attack)`-style reads from the structure, and the
  function picker inserts a call with its help and argument count
  (`odds(n, m)`, `odds(n, m, by)`, `odds(n, m, by, on)`: effect odds as the
  ruleset's effect_odds pipeline scales them, user on target by default). Each
  block edit rewrites only that owner's block of its file (canonical form)
  as one Undo step. Text: the owner's whole file with the script editor's
  editor; typing is written 300 ms after you stop (one Undo step). Text
  that does not parse shows a red banner (file:line:col, Go to) and marks,
  and the blocks keep the last version that parsed (read only until it
  parses again); the list below holds every diagnostic of the logic. Undo /
  Redo act on the owner's source; a step that also changed the battle data
  (the first logic of a battle lists its new source) undoes both.
- **Pipelines & Points** (Logic): pick a pipeline (damage, self_hit, speed,
  accuracy, crit, effect_odds); its steps run top to bottom, which is also
  the order of the random draws. effect_odds (the odds of effect logic's
  `odds(n, m[, by, on])`) is optional: a ruleset that leaves it out shows
  the engine's steps greyed as "engine default (plain odds)", the first
  edit starts from them and **Engine default** gives the pipeline back. Drag a step or use Up / Down; add let, point and roll
  steps; edit the selected step's variable, expression (point, span) and
  clamp, with the range the engine's analysis gives and whether the clamp can
  engage. The Points tab lists each point's holder, sources in the order they
  run, range and how many steps and handlers use it (a used point can't be
  removed). The Damage calculator tab runs one hit (attacker, defender, move,
  levels, roll, critical hit, spread, weather, status, passive, item, traits,
  genes, training, HP, stages) as the engine's damage_preview() does and lists
  every step with its value (point steps also show the value before their
  handlers); unsaved edits count. This page edits the ruleset (Undo / Redo
  act on it); Stats & Stages edits the battle data.
- **Formulas** (Logic): the ruleset's formula slots, named formulas
  (formulas with `"args"` the pipelines call, such as `damage_base`) and
  stat formulas with each one's analysed range
  (and whether the clamp can engage), editable in place, and an evaluator
  that runs a formula exactly as the generated C++ does.
- **Bench** (Logic): battle scenarios (`capsule.bench/1`, in the game
  folder's `bench/` folder, e.g. `bench/wild.json`) run through the
  engine's compiled bench (`apps/battle_bench`), which behaves exactly as the
  game does. New... makes a scenario from the battle data (its first two
  parties, or a wild creature of the first species). The form edits the
  scenario (one Undo step per change; Save scenario writes it): name, format,
  seed, field weather, the parties (a party of the data, or the party's own
  members, picked from the data's species, items, traits and statuses),
  battler state pokes (HP, status, volatiles, stages as `attack +2, defence -1`,
  item), scripted choices (one turn per line: `first`, `run`, `move 2`,
  `move Strike @1`, `switch 1`; `|` between the choices of one turn's field
  positions), answers to effect requests (`learn_move 0`), the stop
  condition and the traces. Run builds the bench from the battle data **as
  saved** (save to include unsaved edits) and runs the scenario in the
  background (Cancel stops it); Run on save runs again whenever the battle
  data, its sources or the scenario are saved; Generator picks the engine's
  default generator or one the reference repo declares in its
  `compat/generators.json` (`capsule.generators/1`, each a source file
  defining `capsule::rng::next16()`, read by the engine's
  `bench_scenario.load_generators()`; with the reference repo, `method1`
  replays its classic goldens); a scenario's `"rng"` picks it. A scenario that
  still writes a poke key the bench retired (C1: `status_turns` is
  `status_counter`, `escalation` is `status_aux`) shows **Migrate
  scenarios**, which renames them in every scenario (one Undo step; Save all
  writes them; `battle FILE bench migrate` does it from the command line). The event list shows the transcript with draw markers
  (the random draws made before each line), the RNG draws, the effect VM's
  steps (owner, hook, pc, file:line:col) and the battle events, filtered by
  type and text; activating a VM row opens Effects on that owner in the
  Text view at that line. Save as expected writes the transcript beside the
  scenario (`NAME.expected.txt`, the scenario's `"expect"`): a regression
  test; Check runs and says PASS, or FAIL with the first differing line.
  The first build configures the engine into the game's
  `build/bench/<generator>` folder (a minute or two); later runs rebuild only
  what changed. Building needs CMake 3.24+ and a C++20 compiler: without
  them the page says what is missing, and scenarios can still be edited and
  saved.
- **Data** ("Other data"): categories, statuses, weathers, passives, items,
  traits, formats and the top-level settings (rules, messages, stats, stage
  names, growth, record layout) as JSON. The condition records and move flags
  (volatiles, side_conditions, field_conditions, move_flags) are shown read
  only until the Conditions and Flags & Tags pages edit them; the studio keeps
  them as they are. The Moves page has one flag box per declared move flag.

The engine knows no game's words: the manifest's `"terms"` give the game's
word for each concept (party, trait, passive, reward, ...; the engine's
neutral defaults otherwise), and texts write `{@concept}` or
`{@concept:many}` for them. New battle data (`battle FILE new`, and the
Blank template of New battle data... and New game...) is the studio's Blank
template: neutral and minimal, the hit points as its only resource (no PP or
other move pool), Health / Power / Guard / Speed, physical and support
categories, one type and one trait, neutral messages, stats equal to the
base values, no stages, condition records, move flags or logic
(`rules.self_hit` names the self-hit's power and category); a game's rules
come from its own data or a template (the engine's Starter, the reference
repo's classic reference).

The Categories page lists the move categories (the stats a damaging one
uses, how many moves take each) and where a damaging move's category comes
from: **the move** (each move names its category) or **its type** (the
structure's `category_by_type`, E11: every type names a damaging category,
the choices being the categories the engine's compiler calls damaging; a
damaging move then states none, a status move still names its own).
Switching to the type mode gives each type its moves' most common damaging
category; switching back writes every move's category out again.

Every list has New, Copy, Rename, Delete and Up / Down (the order is the
engine's index). Renaming follows every reference (learnsets, parties, the
chart, ..., and the effect logic: the entry's own block and every name inside
effect code, rewritten through the AST so only the blocks that change are
rewritten); deleting is refused while something still uses the entry, its
own logic block included. The engine's battle compiler checks the
data on every edit; its message shows under each form. The Formulas page's
Undo is the ruleset's, the content pages' the battle file's.

## Script editor

```
./script-editor path/to/scripts.json        # Windows: script-editor.cmd
```

Scripts, flags and variables (design B-1, B-2, B-4) are text: a scripts
manifest lists the game's `.cscript` sources, and the engine's script
compiler (`tools/script_compiler.py`) turns them into the bank the VM runs.
The editor checks the open buffers with that same compiler about half a
second after you stop typing (or at once with **Check**, F7), so what it
reports is exactly what a build would.

- **Sources** as tabs, with line numbers and syntax colours; Undo / Redo
  work on the source in front. Problems are underlined where they are and
  marked in the line-number gutter (hover for the message).
- **Problems**: every error and warning with its file and line;
  double-click to go there.
- **Outline**: the sources and every script, flag, variable, constant,
  native and map script block of the last check, with lifetimes, types and
  ranges; double-click to go to the declaration.
- **Build settings**: the build variant (`game`) and the variants
  `when game(...)` may name (`games`), the VM's call depth (`stack_depth`,
  deeper call chains are errors), and the asset and world manifests whose
  `text:` keys and map names the check verifies (paths relative to
  scripts.json; empty means not checked).
- **Declare flag or variable**: adds the declaration (lifetime, type,
  range) to a source. **Rename** (F2, on the outline's selection) renames
  a script, flag, variable, constant or native at its declaration and every
  use, in every source, as one undo step per source; labels and message
  texts are left alone. **Add source** adds a new or existing `.cscript`
  file in the manifest's folder.

Save writes the source in front; Save all writes every source and the
manifest. Started without a file, it opens the start window (open, new,
recent, or continue without scripts).

## Project settings

```
./project-settings path/to/reference/project.json   # Windows: project-settings.cmd
```

The **Build settings** panel edits the `"build"` object of a game's project
manifest: the runtime settings the engine compiles into that game (design
A-2, A-5). The engine's `tools/build_settings.py` decides what is valid, so
the panel accepts exactly what the build does.

- Each setting has a checkbox: unchecked means the engine's default (the
  key is left out of the manifest). The VRAM queue's ring sizes (powers of
  two; the arrows double and halve) and its cycles per VBlank, and the GBA's
  `WAITCNT`.
- `WAITCNT` is edited by field (SRAM and ROM wait states, PHI output,
  prefetch) and shown as its raw value. ROM timings other than 3/1 or the
  prefetch buffer off get a caution: the queue's cost table assumes 3/1.
- Every change is one undo step; Save writes the manifest.
- A CMake cache variable of the same name (`CAPSULE_VRAM_BUDGET_CYCLES`, ...)
  overrides every game's value at build time.

[S6] The screen arena (`screen_arena_bytes`, engine UM) is a build setting
too: the bytes of EWRAM the open screens borrow their buffers from (a
multiple of 4; the arrows step by 4).

The **GBA memory** panel [S6] (engine UM) shows a build folder's GBA link
settings, chosen at the top (the configured folders beside the game are
listed, GBA ones first): whether the link fails when a program does not fit
(`CAPSULE_GBA_MEMORY_CHECKS`), the stack reserve
(`CAPSULE_GBA_STACK_RESERVE`) and an arena size overriding every game's
(`CAPSULE_SCREEN_ARENA_BYTES`). They live in the folder's `CMakeCache.txt`
(as cmake-gui edits them) and the next build reads them. **Read the folder's
programs** shows each linked GBA program's memory use as the engine prints it
after a link (EWRAM used and free of 256 KB, IWRAM code and data, the stack
left against the reserve), read with nm; **Open build log...** reads a saved
build's report lines and any memory failure of its link. The chosen
program's notes say what does not fit and the screen arena's share of its
EWRAM.

The **Code page** panel edits the game's code page (C-2, D-20): the file
`"text"` names for the game's language. A game on the engine's default page
gets its own copy first (Give the game its own code page, like `text
codepage import`).

- The 16 x 16 grid shows each code's character and the glyph the game's
  font draws for it; codes after the glyphs are text controls. Pick a code
  to give it a character (Set) or take its character away (Unset).
- The list of characters the game's texts use that the page lacks (asset
  texts, battle names, messages and texts with the game's terms, location
  names, the scripts' inline texts) says where each is used; one can get
  the selected code, or an alias folding it onto mapped text.
- The aliases table lists those folds (Add..., Remove); characters the font
  has no glyph for are named under the grid (the build refuses them).
- The page has its own undo history (Undo / Redo on this tab); Save writes
  the project manifest and the page.

## Audio editor

```
./audio-editor path/to/audio.json   # Windows: audio-editor.cmd
```

[S7] (engine M4, D-34.) The audio editor works on a game's audio manifest
(`audio.json`, `capsule.audio/1`): the file a game's `reference/project.json`
names under `"audio"` (the engine's `capsule_audio_game()` reads the same
key). It is also the Studio's **Audio** page. The engine's
`tools/audio/format.py` decides what is valid: every edit is checked with it
before it becomes an undo step (an edit the build would refuse is refused,
with the reason in the status bar), and the **Problems** list under the tabs
shows what it finds in the whole manifest, unsaved edits included. The
converters are the engine's own: `wav_sample.py` (WAV to sample), `dpcm.py`
(compressed samples decoded for the waveform) and `midi_song.py` (MIDI to
song).

Sound comes from the engine. The editor builds the engine's `audio_render`
for the project's table with `capsule_audio_render()` (CMake and a C++
compiler; the first build compiles the audio core, a few seconds; later
previews only regenerate the table and link) and renders headless through
the real audio core: what you hear is what the GBA mixes, sample for sample
(the optional **HQ** box uses the high-quality desktop mix instead). Previews
play the editor's current data, unsaved edits included: the preview table
holds the songs being played, the project's mixer, players, banks, sets,
keymaps and waves, and only the samples those songs can reach. The build
lives in `build/audio-studio` in the game folder (or a folder of the user's
cache; `CAPSULE_STUDIO_AUDIO_CACHE` names another). **Audio > Build the
renderer** builds it ahead; **Audio > Show the render folder** opens it.

Playing: with Qt Multimedia (`PySide6-Addons`, the toolkit's optional audio
group, installed with the audio editor and the studio) and an audio device,
**Play** plays the WAV in the editor. Without it, without an audio output, or
when Qt Multimedia reports an error while playing, **Play** hands the WAV to
the system's player and runs the playhead at the real speed; **Open in player** and **Save WAV as...**
work everywhere, so the editor stays usable without an audio device.

- **Songs** (the player and viewer): the song list; the header (instrument
  set, priority, reverb: "leave as it is" is `null`) edited with undo; the
  player the preview plays on; the tracks with their notes, programs and end
  (or loop) and **Mute** / **Solo** boxes (a muted track runs a copy of the
  song whose `VOLUME` commands are 0: it keeps its timing and its channels,
  as a mixer mute does). Views: **Timeline** (a piano roll per track colour,
  muted tracks faded, loops dashed, the playhead; a click picks a tick),
  **Commands** (the `.cseq` text form, or one track's commands with their
  ticks), **Tempo** (each `TEMPO` with its frame and time), **Player state**
  (after a render: one lane per channel, coloured by the track holding it,
  the envelope as its height; a click lists that frame's channels: player,
  track, key, velocity, priority, envelope) and **Output** (the rendered
  waveform). **Export text form...** writes the `.cseq` text.
- **Instruments**: the instrument sets (a window of 128 voices of a bank at
  an offset, or a set with its own voices); the window's voices with the
  other sets that share each one (a bank voice belongs to every window over
  it, as the original layout did); one voice's form by kind (sampled with
  fixed rate and reverse, square with sweep and duty, square, wave, noise,
  key split, drum set) and **Kind** to make it another kind (what fits is
  kept); its envelope's curve per frame for a note held so long; **Play
  note** renders one note of it at a key. **Key split**: the keymap on a key
  strip, its runs and what each plays; click a key, shift-click another, give
  them an entry (**Set keys**). **Drum set**: each key's voice (double-click
  to edit it). **Bank windows**: each bank with the windows over it and
  their overlaps. Add a set, a window, a bank, a voice.
- **Samples**: the header (pitch = rate x 1024 at key 60, loop, loop start,
  length) with checks; the waveform with the loop start; **Render note**
  plays it at a key. **Import a WAV**: PCM8 or DPCM4 (lookahead, whole
  blocks), loop start, length, base key and tune; **Convert** shows the
  result first; the data file is written beside the manifest when you save
  (undo before saving leaves no file).
- **MIDI import**: a MIDI file with the options of one conversion config
  line (`-V` volume, `-G` instrument set, `-P` priority, `-R` reverb, `-X`
  48 clocks per beat, `-E` exact gate times, `-N` no compression), written by
  the form or typed. **Convert** reports each track's end tick or loop, the
  frames to the song's end and the notes that come before a track's first
  program change (they play the track's reset voice, near silent); the
  commands with their ticks and the notes on a timeline; **Render** previews
  it with the manifest's instruments. **Import** adds it as the MIDI file and
  its options (the build converts it) or as the converted bytes, optionally
  with a song table entry on a player.
- **Sound effects**: the song table (each number's song, player, name key,
  priority and the player's start check; double-click plays it on its
  player, or from the whole saved table); the players (name, tracks, start
  check; a rename follows into the table) and the mixer. **Two sounds at
  once** starts two numbers a few frames apart in the C++ core
  (`audio_render --sound A --then B@F`, on the render bar's worker) and
  shows who holds each channel frame by frame, the channels the second took
  from the first (marked) and whether its player's start check refused it;
  the render's output plays like any other. Without a C++ toolchain it runs
  at once on the engine's Python model of the core
  (`tests/audio_reference.py`; the studio's tests hold both to the same
  outcome), whose mix has the sampled channels only. **Clips** plays the saved table's clips with their parameters
  (volume, pan, pitch, hold, release, chorus, priority).

## Command line

The same editing works without a display, for scripts, CI and containers.
It needs no Qt, so `python3 toolkit/env.py setup --core-only` is enough
there. From the repository root:

```
./capsule-studio validate data/assets.json
./capsule-studio sprite import data/assets.json "sprite:BALL" ball_*.png --create auto --duration 6
./capsule-studio sprite duration data/assets.json "sprite:BALL" 12 --steps 2
./capsule-studio sprite show data/assets.json "sprite:BALL"
./capsule-studio sprite sheet data/assets.json "sprite:BALL" ball_sheet.png --scale 4
./capsule-studio sprite flips data/assets.json "sprite:HERO" h --steps 4-7     # I3: mirrored steps
./capsule-studio sprite stream data/assets.json "sprite:HERO" on               # I3: one frame in VRAM
./capsule-studio sprite step-table data/assets.json "sprite:HERO" 0 2 1 3      # I3; - removes it
./capsule-studio sprite sheet-frames data/assets.json "sprite:HERO" hero.png   # I3: an indexed sheet's frames
./capsule-studio text set data/assets.json "text:INTRO" --text 'Hello\nworld'
./capsule-studio credits import data/assets.json credits.txt
./capsule-studio credits preview data/assets.json 1 page1.png
```

Code pages (C-2, D-20): which 8-bit code each character of the game's
language gets. GAME is the game's `reference/project.json`, its folder or
any file in it; texts are checked with the page of the game they belong to.

```
./capsule-studio text codepage show .                        # 16x16 grid and aliases
./capsule-studio text codepage check .                       # characters the texts use that the page lacks; status 1
./capsule-studio text codepage import .                      # own copy of the engine's page in data/text/
./capsule-studio text codepage import . fr.codepage.json --language fr --replace
./capsule-studio text codepage set . 0x80 é                  # the font needs a glyph for it (check says)
./capsule-studio text codepage alias . ’ "'"                 # fold onto mapped text; no target removes it
./capsule-studio text codepage unset . 0x80
```

Worlds, maps and tilesets:

```
./capsule-studio world validate data/world.json
./capsule-studio world render data/world.json meadow meadow.png --collision
./capsule-studio world import data/world.json ../other/world.json --maps cave --dry-run
./capsule-studio world groups data/world.json                        # the map group tree
./capsule-studio world group-add data/world.json Overworld/Towns
./capsule-studio world group-move data/world.json meadow Overworld/Towns   # "-" for ungrouped
./capsule-studio map data/world.json route2 new --group Overworld --tilesets outdoor
./capsule-studio map data/world.json route1 new --tilesets outdoor   # a blank map on BG3, BG2, BG1
./capsule-studio map data/world.json route1 tilesets outdoor cave
./capsule-studio map data/world.json meadow layers                   # back to front
./capsule-studio map data/world.json meadow layer-add 0 --priority 0 --purpose canopy
./capsule-studio map data/world.json meadow layer-set 0 --priority 1
./capsule-studio map data/world.json meadow paint outdoor/water 20 14 21 15 --bg 2
./capsule-studio map data/world.json meadow clear 20 14 --bg 1
./capsule-studio map data/world.json meadow cells 20 14 21 15 --elevation 3 --collision 0 --behavior water
./capsule-studio map data/world.json meadow fill outdoor/path 3 3 --bg 2
./capsule-studio map data/world.json meadow border 1 2 outdoor/tree_top outdoor/tree_trunk --bg 2
./capsule-studio tileset data/world.json outdoor import-sheet art.png --metatiles --transparent "#ff00ff"
./capsule-studio tileset data/world.json outdoor transparent art none
./capsule-studio tileset data/world.json outdoor render outdoor.png
./capsule-studio map data/world.json town dictionary all           # I2: every metatile of its tilesets
./capsule-studio map data/world.json town dictionary list          # the metatiles painted
./capsule-studio tileset data/world.json General place --tile 0 --tiles 512 --palette 0 --palettes 6   # I2
./capsule-studio tileset data/world.json General indexed-sheet tiles.png
./capsule-studio tileset data/world.json General bank 1 3 "#62acee"        # bank 1, entry 3
./capsule-studio tileset data/world.json General metatile-add door --entries 0x1021 0x1022 0x1031 0x1032
./capsule-studio tileset data/world.json General entry door 0 33 --bank 1 --hflip
./capsule-studio tileset data/world.json General animations
./capsule-studio tileset data/world.json General animation-set 0 --phase 3 --on-shift reload   # I2 / I3
./capsule-studio tileset data/world.json outdoor animation-add waves water_frames --tiles t:12 --count 2 --from-sheet on
./capsule-studio behaviors data/world.json list
./capsule-studio behaviors data/world.json set fence_east --walls right    # I2: one-way fences
./capsule-studio behaviors data/world.json set shop_counter --kind counter --solid on   # I3
./capsule-studio modes data/world.json set bike turn_frames 8              # I3; bumps / keeps_moving true
```

Encounters (the encounter extension's commands; they save only when the
world compiles):

```
./capsule-studio encounters show data/world.json --when night            # shares with night on
./capsule-studio encounters check data/world.json                        # status 1 on errors
./capsule-studio encounters battle data/world.json ../battle/battle.json
./capsule-studio encounters method-add data/world.json "old lure" --trigger script
./capsule-studio encounters method-set data/world.json swim --vehicles swim
./capsule-studio encounters condition-add data/world.json rain
./capsule-studio encounters table-add data/world.json route1 0 walk --rate 1/10 --label "Tall grass"
./capsule-studio encounters entry-add data/world.json --map route1 0 Sproutle 3-5 --weight 40 --excludes night
./capsule-studio encounters entry-set data/world.json --map route1 0 0 --modifiers "rain x0"
./capsule-studio encounters shared-add data/world.json early_grass --rate 1/10
./capsule-studio encounters entry-add data/world.json --shared early_grass Voltmink 4
./capsule-studio encounters link data/world.json --map route1 0 early_grass
./capsule-studio encounters area data/world.json route1 0 4 4 9 7        # the Encounters brush on a rectangle
./capsule-studio encounters condition-rename data/world.json night dark   # follows every table
```

Scripts (`check` exits with status 1 on errors, and with `--warnings` on
warnings too; editing commands save at once):

```
./capsule-studio script new data/scripts.json
./capsule-studio script check data/scripts.json
./capsule-studio script list data/scripts.json --kind flag
./capsule-studio script declare data/scripts.json var steps --lifetime daily --type u16 --range 0..500
./capsule-studio script declare data/scripts.json flag met_guide --source town.cscript
./capsule-studio script rename data/scripts.json met_guide guide_met
./capsule-studio script add-source data/scripts.json towns/harbor.cscript
./capsule-studio script remove-source data/scripts.json towns/harbor.cscript   # the file stays
./capsule-studio script settings data/scripts.json --game red --stack-depth 16 --assets assets.json
```

Project build settings (`--set`, `--default` and `--waitcnt` save at once;
status 1 when a value is invalid):

```
./capsule-studio project build reference/project.json
./capsule-studio project build reference/project.json --set vram_streaming_slots=128
./capsule-studio project build reference/project.json --default vram_budget_cycles
./capsule-studio project build reference/project.json --waitcnt ws0_first=4 --waitcnt prefetch=on
```

Adding a world to a game (as Add world to game...; a world outside the game
folder needs `--import`, and every map comes along unless `--map` names
some):

```
./capsule-studio project add-world reference/project.json --sandbox --dry-run
./capsule-studio project add-world reference/project.json --sandbox --import --map meadow
./capsule-studio project add-world reference/project.json data/world.json   # a world inside the game
```

Map events (the events extension's commands; they save only when the
world compiles; `-` removes a field):

```
./capsule-studio events show data/world.json --map showcase
./capsule-studio events check data/world.json                         # status 1 on errors
./capsule-studio events add data/world.json town sign 3 3 --script town_sign --facing up
./capsule-studio events add data/world.json town warp 4 9 --to house --warp 0 --transition mosaic
./capsule-studio events set data/world.json town warp 0 --transition -   # the world's default
./capsule-studio events add data/world.json town trigger 5 9 --script rival --var rival_state --value 0
./capsule-studio events set data/world.json town sign 0 --flag found_potion --facing -
./capsule-studio events move data/world.json town sign 0 4 3
./capsule-studio events remove data/world.json town warp 1              # later warps renumbered everywhere
./capsule-studio events area data/world.json house town                 # '-' for its own area
./capsule-studio events scripts data/world.json scripts/scripts.json    # with the names it offers
./capsule-studio events hook-add data/world.json step_counter 4 --phase 1
./capsule-studio events hook-remove data/world.json step_counter
./capsule-studio events set data/world.json town warp 0 --trigger door --direction up   # I3: arrow, door, none
./capsule-studio events set data/world.json center warp 0 --to dynamic                  # I3: the game decides
./capsule-studio events unpainted data/world.json cave on                               # I3
```

Map objects (the objects extension's commands; OBJECT is a local ID or a
name; they save only when the world compiles; `-` removes a field):

```
./capsule-studio objects show data/world.json --map town
./capsule-studio objects check data/world.json                        # status 1 on errors
./capsule-studio objects add data/world.json town 4 5 --name guard --sprite sprite:GUARD --script guard_talk
./capsule-studio objects set data/world.json town guard --movement wander --range 2,1
./capsule-studio objects set data/world.json town guard --sight 4 --until beat_guard   # --sight - : no spotter
./capsule-studio objects move data/world.json town guard 5 5
./capsule-studio objects rename data/world.json town guard sentry
./capsule-studio objects set data/world.json town sentry --trigger player_touch --speed 3 --frequency 4
./capsule-studio objects option data/world.json town sentry through on    # '-': the default
./capsule-studio objects route-set data/world.json town sentry "left 2" "wait 30" "right 2" --skip
./capsule-studio objects route-set data/world.json town sentry --file sentry.route --once
./capsule-studio objects route-clear data/world.json town sentry        # a custom movement becomes static
./capsule-studio objects page-add data/world.json town sentry --when-flag badge_1 --facing left
./capsule-studio objects page-add data/world.json town sentry --when-self A --hidden on
./capsule-studio objects page-set data/world.json town sentry 0 --script sentry_after --when-var coins --when-value 5
./capsule-studio objects route-set data/world.json town sentry up down --page 0
./capsule-studio objects page-move data/world.json town sentry 1 0       # later pages win
./capsule-studio objects page-remove data/world.json town sentry 0
./capsule-studio objects remove data/world.json town sentry            # later local IDs move down
./capsule-studio objects set data/world.json town guard --movement roam --args '{"choices": ["up", "down"]}'   # I3
./capsule-studio objects set data/world.json town guard --movement in_place --args '{"pace": "jog"}'
./capsule-studio objects view data/world.json route1 9 10 7 9           # I3: up to 64 objects; - removes it
./capsule-studio objects stacked data/world.json route1 on              # I3: objects may share a cell
```

Locations (the locations extension's commands; they save only when the
world compiles; `-` removes a field):

```
./capsule-studio locations show data/world.json
./capsule-studio locations check data/world.json                      # status 1 on errors
./capsule-studio locations transition data/world.json wipe_h          # the default warp transition
./capsule-studio locations style-add data/world.json sign --frame banners/sign.png --fill "#e8c890"
./capsule-studio locations style-set data/world.json sign --slide 4 --rename wood
./capsule-studio locations style-remove data/world.json wood          # refused while a location uses it
./capsule-studio locations add data/world.json park --name "Showcase Park" --banner box
./capsule-studio locations set data/world.json park --banner -        # no banner
./capsule-studio locations preview-add data/world.json park sequences/park.json --show first
./capsule-studio locations preview-add data/world.json park sequences/park_night.json --when night
./capsule-studio locations preview-set data/world.json park 1 --when -
./capsule-studio locations preview-remove data/world.json park 1
./capsule-studio locations preview data/world.json park always        # '-' removes the preview
./capsule-studio locations map data/world.json showcase park          # '-': in no location
./capsule-studio locations rename data/world.json park plaza          # its maps follow
./capsule-studio locations remove data/world.json plaza
```

Battle data (editing commands save only when the result compiles):

```
./capsule-studio battle data/battle.json new
./capsule-studio battle data/battle.json new --template starter     # copy a template here instead
./capsule-studio new ../MyGame --template starter    # a new game: MyGame/data/ + MyGame/reference/project.json
./capsule-studio template list                       # blank, starter, the reference repo's (classic), plugins'
./capsule-studio template show starter
./capsule-studio template apply blank data/blank --part structure
./capsule-studio template recorded data/battle.json  # "starter version 1"
./capsule-studio sample list                         # the engine's sample projects (starter_battle, sandbox_map)
./capsule-studio sample copy sandbox_map ../MyWorld  # a sample as a game of your own (data/starter copied along)
./capsule-studio sample check ../MyWorld             # exit 1 when a path leads out of the game folder
./capsule-studio battle data/battle.json validate
./capsule-studio battle data/battle.json info
./capsule-studio battle data/battle.json stats Emberkit 50 --genes 15 --trait Fierce
./capsule-studio battle data/battle.json formula damage_base level=50 power=80 attack=120 defense=90
./capsule-studio battle data/battle.json set moves Fireball power 75
./capsule-studio battle data/battle.json add moves "Fire Burst" --from Fireball
./capsule-studio battle data/battle.json rename types Fire Flame
./capsule-studio battle data/battle.json learn Emberkit 30 "Fire Burst"
./capsule-studio battle data/battle.json party "Novice Kit" add Voltmink 8 --moves "Shock Fang,Arc Bolt" --trait Swift
./capsule-studio battle data/battle.json party "Novice Kit" remove 2
./capsule-studio battle data/battle.json presenter "Scholar Wen" attach Mentor   # at most 2 per party
./capsule-studio battle data/battle.json presenter "Scholar Wen" detach Coach
./capsule-studio battle data/battle.json terms                       # every concept's word
./capsule-studio battle data/battle.json terms party Rival           # plural: + s
./capsule-studio battle data/battle.json terms passive Talent Talents
./capsule-studio battle data/battle.json terms party -               # the engine's default again
./capsule-studio battle data/battle.json intro "Novice Kit" --format Double   # presenters enter, speak, leave
./capsule-studio battle data/battle.json presenter-track Coach --cue exit --side 1   # FRAME X Y ALPHA lines
./capsule-studio battle data/battle.json chart Fire Bio 2
./capsule-studio battle data/battle.json rule damage_base --expr "(level/2 + 4) * power * attack / defense / 40 + 2"
```

Stats (Structure; `battle FILE stat ...`) and the ruleset's pipelines and
points (Logic; `battle FILE pipeline ...`, `point ...`, `damage ...`):

```
./capsule-studio battle data/battle.json validate                    # every target of the game
./capsule-studio battle data/battle.json validate --platform desktop
./capsule-studio battle data/battle.json stat list                   # flags, and "9/10 gba" per target
./capsule-studio battle data/battle.json stat add luck --label Luck --at 3 --base 40 --no-trait
./capsule-studio battle data/battle.json stat set luck odds true      # the effect_odds pipeline's stat
./capsule-studio battle data/battle.json stat move luck down
./capsule-studio battle data/battle.json stat rename luck fortune    # categories, traits, effect logic follow
./capsule-studio battle data/battle.json stat set fortune short Ft
./capsule-studio battle data/battle.json stat set agility order true # takes the flag off the other stats
./capsule-studio battle data/battle.json stat stages critical focus
./capsule-studio battle data/battle.json stat remove fortune
./capsule-studio battle data/battle.json role list                   # ID, width x count, bits, transfer keys
./capsule-studio battle data/battle.json role add gender --custom --width 2 --default 1 --at 4
./capsule-studio battle data/battle.json role add stat_awaken --width 4
./capsule-studio battle data/battle.json role move gender down       # or a position: role move gender 0
./capsule-studio battle data/battle.json role rename gender sex      # custom roles only
./capsule-studio battle data/battle.json role set stat_genes width 4 # null puts the default back
./capsule-studio battle data/battle.json role remove sex            # --force: even though field scripts use it
./capsule-studio battle data/battle.json layout                      # bytes, hash, "60/100 B gba" per target
./capsule-studio battle data/battle.json layout --move-slots 8 --party-size 6
./capsule-studio battle data/battle.json formula                     # every formula with its inputs
./capsule-studio battle data/battle.json rule halve --expr "attack / 2" --range 1 999 --args attack
./capsule-studio battle data/battle.json pipeline show damage        # steps with their analysed ranges
./capsule-studio battle data/battle.json pipeline step add speed --let speed --expr "speed + 1" --range 1 STAT_CAP --at 1
./capsule-studio battle data/battle.json pipeline step move speed 1 down
./capsule-studio battle data/battle.json pipeline step set speed 2 range null
./capsule-studio battle data/battle.json pipeline step remove speed 2
./capsule-studio battle data/battle.json pipeline reset effect_odds  # the engine's plain odds again
./capsule-studio battle data/battle.json point list                  # holder, sources, range, users
./capsule-studio battle data/battle.json point add shield --holder target --sources passive,item --range 1 STAT_CAP
./capsule-studio battle data/battle.json point set shield sources item,passive
./capsule-studio battle data/battle.json damage Emberkit Sproutle Fireball --level 5 --weather Storm --trace
./capsule-studio battle data/battle.json category list               # categories, moves, and the by-type rule
./capsule-studio battle data/battle.json category mode type          # category_by_type: each type decides
./capsule-studio battle data/battle.json category type Water elemental   # a type's damaging category
./capsule-studio battle data/battle.json category mode move          # each move names its category again
```

The effect logic (Logic; `battle FILE effect ...`, `hooks`): OWNER is
`kind:name` (`move:Night Pulse`) or a name only one owner has.

```
./capsule-studio battle data/battle.json effect list --kind passive    # kind:name, file:line, handlers
./capsule-studio battle data/battle.json effect show Recharge          # the block as written, its handlers
./capsule-studio battle data/battle.json effect set Lightfoot --file lightfoot.ceffect   # or --text '...'
./capsule-studio battle data/battle.json effect check                  # file:line:col diagnostics
./capsule-studio battle data/battle.json effect format --write         # canonical text
./capsule-studio battle data/battle.json effect ast "move:Night Pulse" # JSON AST (capsule.effect-ast/1)
./capsule-studio battle data/battle.json effect add move "Gale Kick"   # an empty block, in the moves' file
./capsule-studio battle data/battle.json effect rename "move:Gale Kick" "Tide Slam"   # its logic to another move
./capsule-studio battle data/battle.json effect remove "move:Tide Slam"
./capsule-studio battle data/battle.json hooks --kind weather          # bindings, value, verdicts, draws, points
```

The battle bench (Logic > Bench; `battle FILE bench ...`): SCENARIO is a
name in the game's `bench/` folder, a path relative to the game folder or a
file. The bench builds from the saved battle data into the game's
`build/bench/<generator>` folder (`--cache DIR` for another) and needs CMake
and a C++ compiler; progress goes to stderr.

```
./capsule-studio battle data/battle.json bench new wild --party "Novice Kit" --seed 7   # bench/wild.json
./capsule-studio battle data/battle.json bench list                    # name, title, expected transcript
./capsule-studio battle data/battle.json bench validate                # every scenario's shape (exit 1 on problems)
./capsule-studio battle data/battle.json bench generators              # default and the reference repo's
./capsule-studio battle data/battle.json bench migrate                 # retired poke keys -> their new names
./capsule-studio battle data/battle.json bench run wild --trace rng,vm   # transcript + trace lines (the scenario's "rng")
./capsule-studio battle data/battle.json bench run wild --save-expected   # also writes bench/wild.expected.txt
./capsule-studio battle data/battle.json bench check wild              # PASS, or FAIL with the first differing line
./capsule-studio battle data/battle.json bench build --rng method1     # with the reference repo's Method-1 generator
```

The passive slots per species (Structure > Passive slots):

```
./capsule-studio battle data/battle.json passive-slot list             # slots, uses, the budget
./capsule-studio battle data/battle.json passive-slot add hidden --fixed   # a slot the generation list never rolls
./capsule-studio battle data/battle.json passive-slot rename hidden secret # members naming it follow
./capsule-studio battle data/battle.json passive-slot move secret up   # species' passives follow
./capsule-studio battle data/battle.json passive-slot remove secret    # its place goes from every species
```

`bench run --json` prints the bench's own records (JSON lines). `run` and
`check` exit with status 1 when the bench reports errors or the transcript
differs.

`effect set` replaces one owner's block and leaves the rest of its file as
it is; `effect check` exits with status 1 on an error. The editing commands
save like the others (only when the data compiles for every target).

Stat changes are one Undo step each and move every species' base values
with the stat. A game's target platforms are its `reference/project.json`
`"targets"` (e.g. `["gba", "desktop"]`, default `["gba"]`): the engine allows
10 stats on the GBA and 32 elsewhere, and `stat add` and `validate` check
every target. `damage` runs the engine's damage pipeline step by step with
the point handlers, exactly as `battle::damage_preview()` does (also
`--roll N`, `--crit`, `--spread`, `--status`, `--passive`, `--item`,
`--trait`, `--defender-trait`, `--genes`, `--training`, `--hp`,
`--offense-stage`, `--defense-stage`).

Role changes are one Undo step each and are refused when the engine's
compiler would refuse them (engine role names and fixed widths, custom role
names, widths 1-32, counts up to 255, a default that fits; at most 32 custom
roles; the roles battles need stay). The record's bytes are checked against
each target (100 bytes on the GBA, 256 elsewhere; a party of 6 on the GBA,
8 elsewhere; 8 move slots everywhere). `layout` prints the layout hash: a
role, width, count, stat count or party size change gives a new hash, and
saves made with the old layout no longer load (the Record page warns while
the hash differs from the saved file's). Removing or renaming a role the
game's field scripts use (`role_get` / `role_set` in the scripts manifest's
`.cscript` sources, or a placeholder bound to it with `"record"`; removing a
custom role also moves the IDs of the custom roles after it) lists those uses:
the Record page asks first, and `role remove` / `role rename` refuse without
`--force`. Effect logic reading a role (`holder.role(NAME)`) follows a rename;
removing a role it reads is refused.

Every editing command saves only when the data compiles for every target of
the game (its project.json `"targets"`); otherwise it prints `not saved:`
with the platform (`not saved: gba: ...`). The battle editor's status bar
shows the latest compile result for every target after each edit, Undo and
Redo.

`validate` exits with status 1 when something won't compile, so it can gate
a pipeline. The command line reads PNG images only (with the engine's
reader); the editor reads every format Qt does.

Screens [S6]: `screen-gfx MANIFEST ...` edits tiles, tilemaps and palettes
(`new`, `set`, `color`, `banks`, `paint`, `rows`, `to-cells`, `import`,
`export`, `render`); `screen-plan ...` makes and edits plans (`new`, `add`,
`set`, `remove`, `move`, `mode`, `steps`, `transition`, `fade-style`),
checks them (`check`, `vram`, `frames`), draws them (`render`) and writes
their C++ (`export`); `gba-memory BUILD show|set|report` reads and writes a
build folder's GBA memory settings and prints its programs' memory report
(`--log` reads a build's output). S6b: `screen-plan exit PLAN [CALL [NEXT]]`
sets and shows how a screen leaves; `font metric FONT glyph_height N` sets a
font's glyph height; `interactions WORLD list|check|add|set|remove|move`
edits the world's cell interaction rules.

```
capsule-studio interactions data/world.json add counter talk_clerk --facing up
capsule-studio interactions data/world.json move 3 up
capsule-studio screen-plan exit data/screens/menu.screen.json close_now
capsule-studio screen-gfx data/assets.json import MENU art/menu.png
capsule-studio screen-plan new data/assets.json menu
capsule-studio screen-plan add data/screens/menu.screen.json layers bg=3 screen_block=29 tiles=tiles:MENU tilemap=tilemap:MENU
capsule-studio screen-plan check data/screens/menu.screen.json
capsule-studio screen-plan export data/screens/menu.screen.json src/menu_screen.h
capsule-studio gba-memory build-gba report
```

Audio [S7]: `audio MANIFEST ...` does what the audio editor does. Reading:
`check` (format.py's problems; exit 1 when there are any), `info`, `songs`,
`song KEY [--notes] [--tempo] [--commands] [--track N]`, `sets`, `set KEY`,
`banks`, `voice SET N`, `envelope SET N [--held F]`, `keymaps`,
`split SET N`, `drums SET`, `waves`, `samples`, `sample KEY [--png OUT]`,
`sounds`, `players`. Editing (checked, then saved): `new`, `mixer-set`,
`song-set`, `set-add`, `set-offset`, `bank-add`, `voice-set SET N F=V ...`
(`kind=KIND` makes a new voice of that kind), `voice-add`, `keymap-add`,
`keymap-set KEY FIRST LAST ENTRY`, `wave-add`, `sample-import WAV NAME
[--dpcm --lookahead --no-pad --loop-start --length --key --tune --replace]`,
`sample-set`, `midi-import MIDI NAME [--options=... --instruments --priority
--reverb --volume --form midi|compiled --player --sound-name --report-only
--listing]`, `sound-set`, `sound-add`, `sound-remove`, `player-set`,
`player-add`, `remove KEY`. Playing (builds `audio_render` once): `render
--song KEY [--player --mute 0,2 --solo 1] | --sound N|sound:NAME [--saved] |
--clip N [--clip-pitch ...]` with `--seconds --tail --mono --hq --no-state
--out DIR --state`, `play N`, `state FOLDER [--frame F]` (a render's player
state), `build [--target preview|hq|table]`, `table` (the compiled table's
listing) and `priority A B [--delay F --frames N --every K --wav OUT
--model]` (two sounds at once in the C++ core, or on the reference model
with `--model` or without a toolchain: channels taken, refusals). A
render's summary gives `end_frame` (the frame whose ticks ran the last END)
and `status_end_frame` (the first frame the player's status shows it ended,
what a game's wait sees).

```
capsule-studio audio data/audio/audio.json song song:town --notes --tempo
capsule-studio audio data/audio/audio.json render --song song:town --solo 1 --out renders/town
capsule-studio audio data/audio/audio.json sample-import art/bell.wav bell --dpcm --key c5
capsule-studio audio data/audio/audio.json midi-import music/town.mid town2 --options="-E -V100 -Gtown" --player music
capsule-studio audio data/audio/audio.json voice-set instruments:town 3 attack=200 release=180
capsule-studio audio data/audio/audio.json priority sound:SELECT sound:JINGLE --delay 4
```

Credits text files: pages separated by blank lines, the first line of each
page its heading, the rest its names.

```
DIRECTOR
A. Placeholder

PROGRAMMING
B. Example
C. Sample
```

## How the data is stored

- Imported frames are saved as PNG files next to the manifest, in
  `frames/<sprite name>/`, already at the sprite's size and with
  transparency applied. They are written when you save; undoing an import
  leaves nothing behind. The manifest refers to them as `{"image": "..."}`.
- Sprites made by the editor use `"palette": "auto"`, so the build picks the
  colors from the images (up to 15, plus transparent).
- An animation is a list of steps, each a frame and a duration in display
  frames (1-255, about 16.7 ms each). Several steps can show the same frame,
  so holds and back-and-forth loops cost no extra tiles. When every step has
  the same duration it's stored as `"period"`, otherwise as `"durations"`.
- Credits page *n* is the pair `text:CREDITS HEAD nn` and
  `text:CREDITS NAMES nn`, the keys the credits sequence uses. The prefix can
  be changed in the panel or with `--prefix`.
- Manifests are written with short values on one line and the key order
  kept, so they diff cleanly against hand-written files.

## Code layout

```
capsule_studio/
  core/          editing logic, no Qt anywhere (document + undo, sprites, texts,
                 imaging, previews, worlds, map groups, maps, tilesets, map pictures,
                 importing between worlds, battle data and rulesets, effect logic (logic.py),
                 the battle bench (bench.py),
                 scripts, map events, map objects,
                 locations,
                 project manifests,
                 finding the engine); used by
                 everything below
  cli/           the capsule-studio command; each command group registers itself
  ui/
    panel.py     the contract between an editor panel and its host
    editors/     the panels (animation, text, credits, map, tileset, battle data, presenters,
                 terms, script source, build settings, code page) and dialogs
    shell.py     scene editor window: hosts asset panels, owns File/Edit and validation
    world_shell.py  map editor window: hosts world panels (one document per file,
                 Undo/Redo on the active panel's document)
    world_import.py  the map editor's Import dialog
    battle_shell.py  battle editor window: hosts battle panels (battle file + ruleset)
    script_shell.py  script editor window: sources, problems, outline, settings
    project_shell.py  project settings window: hosts project panels (build settings, GBA memory, code page)
    studio_shell.py  the Studio window: every tool's window above as a page, on one game
    *_app.py     each tool's entry point (studio_app, world_app = map editor, encounter_app,
                 event_app, object_app, location_app, battle_app, script_app, project_app)
  plugins/       the extension host (D-10): plugin.json, calendar versions, the
                 pure-Python rule, loading, what extensions register (no Qt)
  extensions/    the studio's own extensions, loaded through the same host
    encounters/  the encounter editor (panel, map tool, overlay, commands)
    events/      the map events editor (panel, map tool, overlay, commands)
    locations/   the locations editor (panel, hover text, commands)
    objects/     the map objects editor (panel, map tool, overlay, commands)
tests/           core, plugin host and command-line tests (no Qt needed), and
                 test_qt_*.py smoke tests of the windows (skipped without PySide6)
```

## Extensions

Projects extend the tools without forking them (design D-10). This studio
hosts **extensions**: a plugin is a folder with `plugin.json` and a Python
package whose `register(ctx)` adds any of

- panels (tabs in a host: `map-editor`, which the Studio's World page also
  shows; `studio`, the Studio's World page only; a world tool's own id:
  `encounter-editor`, `event-editor`, `object-editor`, `location-editor`;
  `registry.STUDIO_HOSTS` and `registry.MAP_EDITOR` name them),
- map tools (toolbar buttons in the Map tab; a stroke is one undo step),
- map overlays (the Overlay chooser), hover text,
- commands (`capsule-studio <plugin id> <command>`),
- validators (shown under the map and by `world validate`),
- battle templates (plugin API 2: `ctx.add_battle_template("templates/mine")`,
  a folder with a `template.json`, `capsule.template/1`, relative to the
  plugin folder), offered by New game... / New battle data... and
  `capsule-studio template list`.

This studio has plugin API 2 and still loads plugins written for API 1.

```json
{
  "schema": "capsule.plugin/1",
  "id": "acme.day_cycle",
  "version": "2026.10.17.0690",
  "api": 2,
  "requires": {"capsule_studio": ">=2026.10.17.0000"},
  "extension": {"module": "day_cycle.extension"}
}
```

A game lists its plugins in `reference/project.json`
(`"plugins": ["plugins/day_cycle"]`, relative to the game folder);
opening its world in the map editor, a world tool or the Studio loads them,
and `capsule-studio
--project reference/project.json ...` adds their commands. Versions are
zero-padded UTC calendar versions (`YYYY.MM.DD.MMMM`, minutes since 00:00).
Plugins are pure Python only: a plugin folder holding native binaries or
platform wheels, or code importing ctypes / cffi or compiled modules (other
than the standard library's and the studio's PySide6, for UI), is refused
with a message naming the file. A plugin's modules import each other
relatively (`from . import x`). Connectors (compiler-side data, D-10 §4)
are not hosted yet: a plugin with a connector is refused.

A panel edits only through the host's Document and the core functions; it
never opens files or talks to another panel. Another application hosts the
same panels by providing what `ui/panel.py` describes.

## Tests

```
cd editor
python3 -m unittest discover -s tests
```

The `test_qt_*` files need PySide6, so run them in the toolkit environment
(`../.venv/bin/python -m unittest discover -s tests`); they use Qt's
offscreen platform and need no display. In one process the whole suite
needs several GB of memory (more than 4.5 GB has been measured: memory is not
given back between test files). To run it on a smaller machine, run one test
file per process, as CI does:

```
cd editor
../.venv/bin/python ../.github/scripts/run_unit_suites.py
```

The bench tests that build and run
the real bench (CMake and a C++ compiler needed) run only with
`CAPSULE_BENCH_BUILD=1`; the others use a stand-in. The tests of an
imported world (`test_content_imported_world`, and the content class of
`test_qt_world_format`) run only with `CAPSULE_IMPORTED_CONTENT` naming an
imported content folder (`assets-imported/<game>`, private, never part of
this repository); they print how long opening and compiling it took.

## Known limits

- The Qt smoke tests drive the windows offscreen (run against PySide6
  6.11); the rest of the Qt layer is checked by hand.
- Two windows on the same world (the map editor and a world tool, say) do
  not see each other's unsaved changes, and nothing checks for a file
  changed on disk before saving; use one window per world (the Studio's
  World page holds both).
- Studio pages share no documents: unsaved changes on one page reach the
  others when saved.
- The battle bench runs the battle data as saved, and a scenario does not
  record which generator its expected transcript was made with (pick the
  same one for Check). Closing the window does not ask about an unsaved
  scenario (Save scenario writes it).
- Encounters: importing a map brings its encounter tables, but shared
  tables come along as copies inside its own file.
- Text previews follow the engine's layout and colors but aren't an
  emulator; the credits sequence still decides timing and how many pages it
  shows.
- Shape-drawn frames can be played and kept, but not drawn in the editor.
- Credits names are checked for 4 lines, the space under the heading in the
  credits layout.
- Ctrl+Z inside a text field undoes typing in that field; Edit > Undo undoes
  document edits.
- The Text panel hides credits pages under the default `CREDITS` prefix
  only; pages under another prefix also show there.
- Map editor: shape-drawn sheets are shown and used but drawn only in their
  JSON; the world's start is edited in the JSON file for now, and behaviors
  are added and changed but not renamed or removed (maps name them); the
  first map added to a world without a start becomes the start. Renaming a
  metatile changes several files; Undo reverts it in the active panel's
  file only. Door animations and cell overrides (I3) are runtime functions
  the game's code drives (map::set_cell_override(), load_tiles()); they have
  no world data to edit, so the studio shows door warps only. A fixed
  tileset's metatiles are drawn with the tilesets most maps load with it;
  a map loading another set draws its own pictures from its own compile.
- Battle editor: passives, items, statuses, weathers and formats are edited
  as JSON (with the compiler's checks), not with dedicated forms yet; sprite
  keys are typed, not picked from an asset manifest; there is no battle
  preview in the editor (the engine's sandbox plays the data).
