# CapsuleCreatures Studio

The development home for CapsuleCreatures projects: machine setup, and the
asset tools and editor as they're built. The runtime engine
(`CapsuleCreatures_Engine`) stays its own repository; both are submodules of
the `CapsuleCreatures` umbrella repository (`toolkit/` and `engine/`, D-37),
whose root launchers call into this toolkit.

## Layout

```
install/            sets up a machine to build and run projects for GBA and desktop
  install.sh        Linux (Arch-, Debian-, Fedora-based), macOS, Haiku (desktop only)
  install.ps1       Windows 10/11
  SUPPORT.md        what each OS gets, how far it's tested, and what isn't supported
editor/             the CapsuleCreatures editor (Python; see editor/README.md)
  capsule_studio/   core (no UI), cli (capsule-studio command), ui (PySide6 panels),
                    plugins (extension host), extensions (the studio's own extensions)
toolkit/            the toolkit's Python environment
  env.py            creates and updates .venv, runs the tools in it (standard library only)
  requirements/     pinned packages per group: core (headless tools), ui (editors), audio (playing sound in them)
studio              starts the Studio, every editor in one window (studio.cmd on Windows)
scene-editor        starts the scene editor (scene-editor.cmd on Windows)
map-editor          starts the map editor (map-editor.cmd on Windows)
battle-editor       starts the battle editor (battle-editor.cmd on Windows)
battle-structure    starts the battle editor on its Structure pages (battle-structure.cmd on Windows)
battle-logic        starts the battle editor on its Logic pages (battle-logic.cmd on Windows)
encounter-editor    starts the encounter editor (encounter-editor.cmd on Windows)
event-editor        starts the event editor (event-editor.cmd on Windows)
object-editor       starts the object editor (object-editor.cmd on Windows)
location-editor     starts the location editor (location-editor.cmd on Windows)
script-editor       starts the script editor (script-editor.cmd on Windows)
project-settings    starts the project settings window (project-settings.cmd on Windows)
audio-editor        starts the audio editor: songs, instruments, samples, MIDI import, sound effects (audio-editor.cmd)
capsule-studio      the command-line tools (capsule-studio.cmd on Windows)
Doxyfile            documentation rule for the Python sources (warnings are errors)
```

Planned (design change to D-1, see the project's design spec):

- `tools/`: asset compilers (fonts, input maps, then maps, tilesets, and so on),
  moved out of the engine. Until then the editor imports the engine's own
  compilers, so it validates exactly as the build does.

## Editors

The **Studio** shows every editor in one window, on one game (opened
through its `reference/project.json`), and each editor also runs by itself:

- the scene editor edits sprite frame animations (frames, durations, bitmap
  import), text and credits, text boxes and menus, and full-screen scenes'
  graphics (tiles, tilemaps, palettes) and screen plans (layers, windows,
  sprites and transitions, previewed and exported as C++);
- the map editor edits worlds, maps and tilesets, with the map tools and
  overlays of the world tools, and the world's settings (behaviors, movement
  modes, doors and draw order, cell interaction rules);
- the world tools edit the rest of a world, each on its own or as a tab of
  the Studio's World page next to the map: the encounter editor
  (encounter tables), the event editor (map events and warp transitions),
  the object editor (map objects with their event pages, triggers and move
  routes) and the location editor (locations with their name banners and
  previews);
- the battle editor edits battle data: its content (species, moves, types,
  parties, presenters), its structure (the game's terms, its code page, and
  more to come; stats from the command line) and its logic (formulas;
  pipelines, points and a damage calculator from the command line; effect
  logic; a test bench that runs battle scenarios through the engine's
  compiled battle and keeps expected transcripts), in one window with a
  navigator of the three groups;
- the script editor edits a game's `.cscript` sources, flags and variables,
  checked live with the engine's script compiler;
- the project settings window edits a game's build settings and code page (its
  `reference/project.json`), and a build folder's GBA memory settings with its
  programs' memory report.

Each editor is made of panels that both its own window and the Studio host,
and everything it does is also available from the `capsule-studio` command
line for scripts, CI and containers.

**Rule:** every new core engine feature ships with its editor support, in
the same change as the engine module and its sandbox app. The editing logic
goes in `capsule_studio.core`, command-line access in `capsule_studio.cli`,
and the panel in `capsule_studio/ui/editors/`.

```
./studio path/to/reference/project.json    # Windows: studio.cmd
./scene-editor path/to/assets.json          # Windows: scene-editor.cmd
./map-editor path/to/world.json             # Windows: map-editor.cmd
./battle-editor path/to/battle.json         # Windows: battle-editor.cmd
./battle-structure path/to/battle.json      # the same, Structure pages first
./encounter-editor path/to/world.json       # Windows: encounter-editor.cmd
./event-editor path/to/world.json           # Windows: event-editor.cmd
./object-editor path/to/world.json          # Windows: object-editor.cmd
./location-editor path/to/world.json        # Windows: location-editor.cmd
./script-editor path/to/scripts.json        # Windows: script-editor.cmd
./project-settings path/to/reference/project.json   # Windows: project-settings.cmd
./audio-editor path/to/audio.json           # Windows: audio-editor.cmd
./capsule-studio validate path/to/assets.json
```

## The toolkit environment

Every tool runs from one Python virtual environment, `.venv/` in this
folder, so nothing is ever installed by hand or system-wide, and no
administrator rights are needed. The installers create it; if they haven't
run, the launchers create it on first use. It holds exactly the versions
pinned in `toolkit/requirements/`, installed as binary wheels only (no
package code runs while installing). When a pin changes, the next launch
updates the environment; if it is ever broken (say the system Python was
upgraded underneath it), the next launch rebuilds it.

```
python3 toolkit/env.py status          # what is installed
python3 toolkit/env.py setup           # create or update it now
python3 toolkit/env.py setup --reset   # rebuild it from scratch
python3 toolkit/env.py setup --core-only   # headless tools only (CI, containers)
```

It needs Python 3.10 or later; if `python3` is older, the toolkit looks for
a newer one (`python3.12`, the Windows `py` launcher, ...) and uses that.

The audio editor and the studio window also install the **audio** group
(`PySide6-Addons`, Qt Multimedia, at the same version as PySide6), so
**Play** sounds inside the editor; `setup` installs it too. It is optional:
when it can't be installed (no wheel for the platform, a `wheels/` folder
without it) the toolkit warns, the tools start anyway, and Play hands the WAV
to the system's player, as it also does on a machine without an audio output
device. A launch doesn't try a failed audio install again; `setup` does, and
`status` shows it as "install failed (optional ...)" without failing
`status --check`.

**Machines without internet access.** On a connected machine, download the
pinned packages as wheel files, for the target platform if it differs:

```
python3 toolkit/env.py fetch-wheels                              # this platform
python3 toolkit/env.py fetch-wheels --platform win_amd64         # e.g. for Windows
python3 toolkit/env.py fetch-wheels --platform manylinux_2_28_x86_64 --python-version 3.12
```

Copy the resulting `wheels/` folder into this folder on the target machine
(or point `CAPSULE_STUDIO_WHEELS` at it). Whenever `wheels/` holds wheel
files, the toolkit installs from them and never contacts the network;
`setup --offline` makes that a requirement. `wheels/` is ignored by git.

## Set up a machine

Linux, macOS or Haiku:

```
install/install.sh --dry-run     # see every step first
install/install.sh               # then install
```

Windows (PowerShell):

```
powershell -ExecutionPolicy Bypass -File install\install.ps1 -DryRun
powershell -ExecutionPolicy Bypass -File install\install.ps1
```

`--gba-only` / `--desktop-only` (`-GbaOnly` / `-DesktopOnly` on Windows) limit
what gets installed. Installers ask before changing anything, can be re-run
safely and never upgrade the rest of your system. Details per OS are in
`install/SUPPORT.md`.

## Working copies

This repository is the `toolkit/` submodule of the `CapsuleCreatures`
umbrella repository (see the umbrella's `docs/WORKSPACE.md`, D-37). The
umbrella is checked out twice, side by side in the workspace folder, and the
editor finds the engine as its sibling `../engine` (or through
`CAPSULE_ENGINE`; see `editor/README.md`):

- `CapsuleCreatures-work/toolkit/` is the editable copy. Changes are made and
  pushed from here, after every change has been reviewed by a human before it
  is committed.
- `CapsuleCreatures/toolkit/` is a read-only reference checkout. It is updated
  only by hand (`git pull`, `git submodule update`) by the developer, after
  review.

The toolkit environment (`.venv/`) is created in this folder, so the umbrella's
`CapsuleCreatures-work/toolkit/.venv` is the one environment of the work
copy.

## Credits

The GBA toolchain is devkitPro's (https://devkitpro.org). The installers follow
devkitPro's published instructions and download their official installers.
