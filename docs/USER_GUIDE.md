# CapsuleCreatures Studio: user guide

The toolkit is where you make a CapsuleCreatures game. Its **Studio** holds
every editor in one window, on one game, and each editor also runs on its
own. Everything the editors do is also on the `capsule-studio` command line.

New to the project? Start with the umbrella repository's
[getting-started guide](https://github.com/TheWildDeadHero/CapsuleCreatures/blob/main/docs/GETTING_STARTED.md).
This guide explains the Studio's pages and editors. The full reference for
each editor, with every option, is [`editor/README.md`](../editor/README.md).

## Starting the tools

| You have | Start the Studio | Start one editor |
|---|---|---|
| a prebuilt download | `studio` (Linux), `studio.exe` (Windows), `CapsuleStudio.app` (macOS) | `map-editor`, `battle-editor`, ... in the same folder (`.cmd` on Windows); macOS: `CapsuleStudio.app/Contents/MacOS/studio map-editor` |
| a source checkout | `./studio` in the umbrella repository (`studio.cmd` on Windows) | `./map-editor`, `./battle-editor`, ... (`.cmd` on Windows) |

Give the Studio a game's `reference/project.json` to open it at once
(`./studio path/to/reference/project.json`), and `--page NAME` to show one
page first (`world`, `assets`, `scripts`, `battle`, `project` or `audio`).
Started without a game, it opens a start window: **Open project...**,
**New game...**, your recent projects, and **Continue without a project**.
Every launcher prints its options with `--help`.

## A game's files

A game is a folder. Its `reference/project.json` (the project manifest)
names the game's data files, relative to the game folder:

| Key | The file | Studio page |
|---|---|---|
| `maps` | the world (`capsule.world/1`) with its tilesets and maps | World |
| `assets` | the asset manifest (`capsule.assets/1`): sprites, texts, fonts, text boxes, screens | Assets |
| `scripts` | the scripts manifest (`capsule.scripts/1`) and its `.cscript` sources | Scripts |
| `battle` | the battle data (`capsule.battle/1`), with its structure, ruleset and effect logic | Battle |
| `audio` | the audio manifest (`capsule.audio/1`) | Audio |

Its `"sources"` list the game's C++ scene code (in `src/`, relative to the
game folder) and `"rom"` holds the GBA ROM header (title, game code,
maker). The project manifest itself, with the game's build settings and code page,
is the **Project** page. `capsule-studio project files reference/project.json`
lists what a game names. A page whose file the game does not name starts
empty.

**Studio > Add world to game...** (also in the World page's **File** menu)
gives the open game a world: the map sandbox's (the engine's sample world)
or any `world.json` you pick. A world inside the game folder is named as it
is. A world from elsewhere is imported first, into the game's own world
(`data/world.json` when the game has none): the import dialog opens with
every map ticked, and the imported world's encounters use the game's battle
data. The Studio then writes `"maps"` into `reference/project.json` and
opens the world on the World page. On the command line:
`capsule-studio project add-world reference/project.json --sandbox --import`
(or a `world.json` instead of `--sandbox`; `--map NAME` imports only some
maps, `--dry-run` says what would happen).

Every new game has a world (see [New games from a template](#new-games-from-a-template)).
A game without one (made with an older toolkit, or whose `"maps"` was taken
out) shows **This game has no world yet** on its World page instead of the
map editor: **Create a new world** makes an empty `data/world.json`, points
it at the game's battle data, names it in `reference/project.json` and opens
it (add a tileset on the Tileset tab, then a map on the Map tab: the game
builds once its world has a map); **Add an existing world...** is **Add
world to game...**.

## New games from a template

**New game...** (on the start window, or **Studio > New game...**) makes a
game folder from a template and opens it. Pick a template, choose a new or
empty folder with **Browse...**, give the game a name (optional) and click
**Create**. The template's files go into `data/`, the game gets a world and
a first scene, and `reference/project.json` names the world, the battle
data, the assets and the scene. The Studio then opens the game on its
**World** page, with the first map on the **Map** tab.

The world is small and made of simple shapes, so the game builds at once and
the map editor has something to paint with:

- `data/world.json`, the world, pointed at the game's battle data;
- `data/tilesets/basic.json`, the tileset **basic**: three metatiles drawn
  from plain shapes (no image file): **ground** (green), **path** (sand) and
  **wall** (grey stone);
- `data/maps/start.json`, the map **start**: 16 x 16 metatiles (a little
  more than the GBA's screen), ground with a path across the middle and a
  wall around the edge, blocked on the attribute layer; outside the map
  shows wall. The game starts in the middle of the path, facing down.

Paint over it, add tilesets and maps, or replace it: **Add world to game...**
imports another world's maps into it.

The first scene makes the game run as soon as it is built:

- `src/game.cpp`, the scene: the player stands on the world's start (the
  map **start**), walks with the D-pad, runs while B is held and stops at the
  wall; a text box names the game until A closes it. It is short and
  commented, the place to start the game's own code;
- the player's sprite, **sprite:PLAYER** (simple shapes) in the game's asset
  manifest: added to the template's `data/assets.json`, or a new
  `data/assets.json` when the template has none (Blank);
- in `reference/project.json`: `"sources": ["src/game.cpp"]` and `"rom"`,
  the ROM header: the game's name in capitals (letters, digits and spaces,
  at most 12) as its title, the game code `CNEW` and the maker `00`. Give
  your own before you share the ROM.

The game's `"name"` keeps letters, digits and `_` (`My Game` becomes
`My_Game`): the engine builds it as `capsule_<name>`. Build and run it with
the umbrella's `./build PRESET --game FOLDER` (`./build gba-release --game
~/Games/MyGame`: `MyGame/build/gba-release/capsule_MyGame.gba`); the
umbrella's getting-started guide (B7) has every step. The **GBA memory**
page lists those build folders. `capsule-studio new GAME --template NAME`
on the command line makes the same world and scene.

| Template | What you get |
|---|---|
| **Starter** | the engine's Starter sample: nine stats with HP, MP and EP pools, nine types, nine creatures with moves, talents and charms, three rivals and simple-shape art; a complete small game to change |
| **Blank** | the least battle data that compiles: hit points, Power, Guard and Speed, physical and support moves, one type and one trait |

Templates hold battle data and assets; the world and the first scene are
the same small ones for every template. Scripts and audio are added later. The battle
editor's **File > New battle data...** opens the same dialog for battle data
alone. Nothing is ever overwritten.

## Sample projects

**Open a sample...** (on the start window, beside **New game...**, or
**Studio > Open a sample...**) copies one of the engine's two sample
programs into a folder of your own, as a game you can change and build:

| Sample | What it shows | Opens on |
|---|---|---|
| **Starter Battle** | the Starter game's battles: three rivals and unowned creatures in 1 vs 1 and 2 vs 2, recruiting, healing, the storage boxes and the AI playing both sides | the **Battle** page |
| **Map Sandbox** | the overworld: a small world of maps with scripts, signs, people, warps, encounters and field actions, a debug overlay and a collision view | the **World** page, on the map the world starts on |

Pick a sample (each row has its one line), choose a new or empty folder
with **Browse...**, give the game a name (optional) and click **Copy and
open**. The copy holds:

- every file of the sample's folder: `reference/project.json`, `src/` (its
  scene code), `data/` (the Map Sandbox's world, tilesets, maps, encounters,
  scripts and assets) and a `README.md` with the controls;
- `data/starter/`, its own copy of the Starter battle data the sample plays
  (`battle.json`, `structure.json`, `ruleset.json`, `effects/`,
  `assets.json`). The project manifest, the world and the scripts point at
  it, so nothing in the copy reads the engine's files;
- the same name rules as **New game...**: `"name"` keeps letters, digits and
  `_` (the folder's name when you give none), the ROM header's title is the
  name in capitals and its game code `CNEW`.

The Studio refuses a folder that has files, or one inside the engine or
the Studio's own folder. Build the copy like any game, with the umbrella's
`./build gba-release --game FOLDER` (or `desktop-release`): it plays as the
sample does. On the command line, `capsule-studio sample list` lists the
samples, `capsule-studio sample copy NAME FOLDER [--name N]` makes the same
copy and `capsule-studio sample check FOLDER` says whether anything in a
game folder leads out of it.

## The Studio window

The page list on the left goes to each part of the game; Ctrl+1 to Ctrl+6
go to a page. A page with unsaved changes is marked `*`, and its tooltip
names its file. The menu bar shows the **Studio** menu (Open project..., New
game..., Add world to game..., the pages, Quit), then the menus of the page in front, then
**Help**. Only the page in front takes keyboard shortcuts, so Ctrl+S saves
what you are looking at.

Each page keeps its own copy of its files: a change on one page reaches the
others once it is saved (a flag declared on the Scripts page shows in the
Objects tab after Save). Closing the Studio, or opening another game, asks
about every page with unsaved changes.

Every editor has **Open**, **Save**, **Undo** and **Redo** in its toolbar
(and the same in its File and Edit menus: Ctrl+O, Ctrl+S, Ctrl+Z, Ctrl+Y).
The World and Battle pages, which edit several files, add **Save all**
(Ctrl+Shift+S). Everything is checked with the engine's own compilers as you
edit, so what an editor accepts is what the build accepts; the status bar
says when a file compiles.

Panels side by side or stacked (the page list, a list beside its form, a map
beside its layers and palette, a table over its preview) have a handle
between them, drawn as two short lines: drag it to give one panel more room.
The panels share a window's new space until you drag a handle; after that
they keep the sizes you gave them. A panel whose content does not fit shows
scroll bars, so the Studio and every editor work in a window as small as
800 x 540.

### World

The map editor and the world tools, on the game's world:

| Tab | What it edits |
|---|---|
| Map | the maps: the map list (with groups as folders), tile layers and the attribute layer (collision, elevation, behavior, encounters, environment tag), the border; paint, rectangles, fill, pick, zoom |
| Tileset | the tilesets: sheet images (PNG, BMP, GIF, JPEG), metatiles made in the metatile maker or from sheet blocks, animations |
| Levels | the world's 16 elevation levels: which levels meet, what arriving does, sprite priority |
| Movement modes | how the walker moves: walking and running speeds, what each mode may enter (on foot, swimming, ...) |
| Field | object kinds, map tags, flight points, darkness and escape points |
| Behaviors | the terrain classes cells use: solid, passable, slide, ledge, push, walls |
| Doors and draw order | door animations bound to metatiles, and which objects draw in front |
| Interactions | what pressing A while facing a cell does when no object or sign answers: rules that start a script |
| Encounters | encounter tables per map and slot, methods, conditions, the world's battle data (**Battle data...**) |
| Events | warps, triggers, signs and step hooks, and warp transitions |
| Locations | locations, their name banners and previews |
| Objects | characters, spotters and pickups, with their pages, triggers and move routes |
| Override sets | a map's named sets of cell changes that scripts apply and clear (say, a gate that opens) |

**File > New world...** starts a world in a folder; **File > Import from
another world...** brings maps and tilesets in from another world, with the
tilesets, images and behaviors they need. **File > Add world to game...**
makes a world the game's own (see [A game's files](#a-games-files)).

With no world open, the page (and the map editor) says so instead of showing
the tabs, with buttons that make or open one: **Create a new world** and
**Add an existing world...** for a game without a world, **New world...**
and **Open world...** in the map editor. A button that cannot do anything
yet (say, **Remove** with nothing chosen) says why in the status bar. A
panel with nothing to show greys its fields; its lists and pages still
scroll.

### Assets

The scene editor, on the asset manifest: **Animation** (sprite frames and
how long each shows, imported from images), **Doors**, **Text** (checked
against the game's code page and previewed in its font), **Credits**,
**Text tables**, **Fonts**, **Text boxes**, **Menu styles**, **Screen
graphics** (tiles, tilemaps and palettes of full-screen scenes),
**Screen plans** (a screen's layers, windows, sprites and transitions,
exported as C++) and **Manifest** (included files and text tables).

Four pages after **Animation** are the battle animation tools (the
engine's generic parts, nothing game-specific):

- **Anim scripts**: open an animation bank (a `.canim` text or a bank
  file; **Sample** is the engine sandbox's) and step a script frame by
  frame as the engine's player runs it: the commands run on each frame,
  the player's state (run or wait mode, arguments, call stack, the visual
  and sound counts) and a timeline of sprites, tasks, sound, background,
  control and the game's own commands. How long each sprite or task lives
  is the game's code: set it per symbol (frames, or an argument slot).
- **Affine anims**: the commands that scale and rotate a sprite (frames,
  loops, jumps, end), with a preview that steps them as the engine does
  and shows each step's matrix. **Save as...** names the file
  (`NAME.affine.json`; saved with the manifest from then on) and
  **Export C++...** writes the `af::Cmd` arrays a game includes.
- **Scanline effects**: a register (a layer's scroll, window 0's edges,
  the blend weights) given a value per line by the engine's wave, a weight
  ramp or a growing window; the screen, the table and a plot, frame by
  frame.
- **Anim scenes**: the engine sandbox's scenes as the engine draws them,
  through its `capsule_anim_view` (built with the engine's tests; **Find**
  looks in the engine's build folders, **Browse...** picks it).

**VM extensions** (after the battle animation tools) shows a game's VM
extension manifests (`capsule.vm-ext/1`): the opcodes a game adds to the
engine's script machines, each an *alias* of the engine's generic steps
(data only) or a *native* function with the reason no generic step works.
**Open manifests...** reads a game's manifests (**Sample** is the engine
sandbox's); **Add usage...** adds the banks' usage records (how often each
opcode is emitted) and **Add GBA sizes...** an `nm -S -C` listing of a GBA
build (each native's bytes). The left side shows each command table's
progress (aliases and their share, natives left, opcodes no bank uses),
the middle the opcodes (filter by kind, name or reason), the right the
chosen opcode's operands and steps or reason, and the engine's checks.
**Copy report** puts the natives with their reasons, owners and sizes on
the clipboard. The manifests are the game's source files: the view does
not edit them.

### Scripts

The script editor, on the scripts manifest: the `.cscript` sources as tabs
with line numbers and colours, the game's flags and variables, its
**Settings** and **Placeholders**. The engine's script compiler checks the
sources half a second after you stop typing (or at once with **Check**, F7).

### Battle

The battle editor, with a navigator of three groups. Page titles use the
game's own words, so a Starter game says Rivals and Talents.

- **Content**: species, moves, types, parties, presenters, passives and
  items, messages and more.
- **Structure**: the record layout, stats, resources, stages, categories, the
  type chart, conditions, turn order, growth, pockets, recruiting, storage,
  field effects and actions, terms and text.
- **Logic**: effect logic, formulas, pipelines and points (with a damage
  calculator), AI, and the **Bench**, which runs battle scenarios through
  the engine's compiled battle and keeps the expected transcripts (it needs
  the full install: CMake and a C++ compiler).

### Project

The project settings: **Build settings** (the engine settings compiled
into this game: VRAM upload queue sizes, ROM wait states, the screen arena),
**GBA memory** (a build folder's memory report, from a GBA build) and
**Code page** (which 8-bit code each character of the game's language gets).

### Audio

The audio editor: **Songs**, **Instruments**, **Samples** (from WAV files),
**MIDI import** and **Sound effects**. **Play** renders a sound with the
engine's own audio code (this needs the full install's CMake and compiler);
the sound plays inside the window when Qt Multimedia is installed, and
through your system's player otherwise. The prebuilt downloads always use
the system's player.

## The editors on their own

Each page is also a window of its own, opened on one file:

| Launcher | Opens | Same as |
|---|---|---|
| `map-editor` | `world.json` | the World page's Map and Tileset tabs |
| `encounter-editor`, `event-editor`, `object-editor`, `location-editor` | `world.json` | one World tab each |
| `scene-editor` | `assets.json` | the Assets page |
| `script-editor` | `scripts.json` | the Scripts page |
| `battle-editor` | `battle.json` | the Battle page (`battle-structure` and `battle-logic` open it on those groups) |
| `project-settings` | `reference/project.json` | the Project page |
| `audio-editor` | `audio.json` | the Audio page |

Started without a file, each opens a small start window (open, new, recent,
or continue without a file). Edit a world in one window at a time: the map
editor and a world tool open on the same world do not see each other's
unsaved changes. The Studio's World page holds them all in one window.

## The command line

`capsule-studio --help` lists the command groups (`validate`, `sprite`,
`text`, `world`, `map`, `tileset`, `battle`, `script`, `project`, `new`,
`template`, `sample` and more), and `capsule-studio GROUP --help` their actions. A few
examples:

```
capsule-studio template list                                  # the templates New game... offers
capsule-studio new MyGame --template starter                  # a new game folder
capsule-studio sample copy sandbox_map MyWorld                # a sample project as your own game
capsule-studio project files MyGame/reference/project.json    # what a game names
capsule-studio world validate MyGame/data/world.json          # compile a world with the engine
capsule-studio world render MyGame/data/world.json meadow meadow.png   # draw a map to a PNG
```

The command line needs no display and no Qt, so it runs in scripts, CI and
containers. [`editor/README.md`](../editor/README.md#command-line) lists
every command.

## The toolkit environment

In a source checkout, every tool runs from one Python virtual environment,
`toolkit/.venv`, so nothing is installed by hand or system-wide, and no
administrator rights are needed:

- `./setup` creates it. If setup has not run, the first launch of any tool
  creates it.
- It holds exactly the versions pinned in `toolkit/requirements/`
  (`core.txt` for the command line, `ui.txt` for the editors, `audio.txt`
  for playing sound in the window), installed as binary wheels only, so no
  package code runs while installing.
- When a pin changes, the next launch updates it. If it breaks (say the
  system's Python was upgraded underneath it), the next launch rebuilds it.
- It needs Python 3.10 or later. If `python3` is older, the toolkit looks
  for a newer one (`python3.12`, the Windows `py` launcher, ...).
- The audio group (Qt Multimedia) is optional: when it cannot be installed,
  the tools start anyway and **Play** uses the system's player.

```
python3 toolkit/env.py status               # what is installed
python3 toolkit/env.py setup                # create or update it now
python3 toolkit/env.py setup --reset        # rebuild it from scratch
python3 toolkit/env.py setup --core-only    # the command-line tools only (CI, containers)
python3 toolkit/env.py fetch-wheels         # download the pinned packages for an offline machine
```

Run these in the `toolkit` folder. For a machine without internet access,
copy the downloaded `wheels/` folder into `toolkit/` (or point
`CAPSULE_STUDIO_WHEELS` at it): the toolkit then installs from it and never
contacts the network. `CAPSULE_STUDIO_VENV` puts the environment somewhere
else.

The prebuilt downloads carry their own Python, Qt and a copy of the engine,
so they need none of this.

**Finding the engine.** The editors use the engine's compilers, fonts and
limits. They look for it in `CAPSULE_ENGINE`, then in `../engine` (the
umbrella's `engine/` submodule), then in a standalone engine clone beside a
standalone toolkit clone. A prebuilt download uses its own copy unless
`CAPSULE_ENGINE` names another, for example your checkout's `engine` folder.

## Extensions

A game can extend the Studio without changing the toolkit. An extension
(a plugin) is a folder with a `plugin.json` and a pure-Python package whose
`register(ctx)` adds panels (tabs on the World page or a world tool), map
tools, map overlays, hover text, command-line commands, validators or
battle templates. A game lists its plugins in `reference/project.json`
(`"plugins": ["plugins/day_cycle"]`), and opening the game loads them. The
Studio's own world tools (encounters, events, objects, locations, override
sets) are extensions too, loaded the same way. Plugins with native code are refused.
[`editor/README.md`](../editor/README.md#extensions) has the plugin format.

## Known limits

- The Studio adds a world to a game (**Add world to game...**), but not yet
  a scripts or audio file: add that key (`"scripts"`, `"audio"`) to the
  game's `reference/project.json` in a text editor.
- Two windows on the same world do not see each other's unsaved changes, and
  nothing checks for a file changed on disk before saving.
- The Bench, Play in the audio editor and GBA memory reports need the full
  install (CMake, a C++ compiler, devkitARM).
- [`editor/README.md`](../editor/README.md#known-limits) lists the rest.
