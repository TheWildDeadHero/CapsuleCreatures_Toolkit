# Changelog

All notable changes to the CapsuleCreatures Toolkit. Versions are calendar
versions, `YYYY.MM.DD.MMMM` (the UTC date and the minutes since midnight).

## YYYY.MM.DD.MMMM: first public release

The first public release of the toolkit, licensed under the Mozilla Public
License 2.0.

- **The Studio**: every editor in one window, on one game, with the World,
  Assets, Scripts, Battle, Project and Audio pages, **New game...** from
  the Starter or Blank template, and **Add world to game...** (the map
  sandbox's world or any other, imported into the game when it is outside
  it; `capsule-studio project add-world` on the command line). Every new
  game, from any template and from the Studio, the start window or
  `capsule-studio new`, gets a small world that builds: one tileset of
  simple shapes (ground, path, wall) and the map `start`; the Studio opens
  it on the World page. It also gets a first scene, so it builds and runs at
  once (the umbrella's `./build PRESET --game FOLDER`): `src/game.cpp`, where
  the player walks the start map with the D-pad and a text box names the
  game, the player's sprite in `data/assets.json`, and `"sources"` and a ROM
  header in `reference/project.json`; the game's name keeps the letters,
  digits and `_` a build target can hold. A game without a world (made before) shows **This
  game has no world yet** on its World page, with **Create a new world**
  (an empty `data/world.json`) and **Add an existing world...**.
  **Open a sample...** (start window and Studio menu; `capsule-studio sample
  list | copy | check`) copies the engine's Starter Battle or Map Sandbox
  into a folder of the user's as a game of its own, with its own copy of
  the Starter data and a build-safe name, and opens it.
- **Editors**, each also on its own: the map editor (maps, tilesets, map
  groups, importing from another world) and the world tools (levels,
  movement modes, field, behaviors, doors and draw order, interactions,
  encounters, events, locations, objects, override sets); the scene editor
  (sprites and animations, texts, credits, fonts, text boxes, menus, screen
  graphics and screen plans); the script editor; the battle editor (content,
  structure and logic, with a damage calculator and the battle bench); the
  project settings (build settings, GBA memory, code page); the audio editor
  (songs, instruments, samples, MIDI import, sound effects).
- **The command line**: `capsule-studio` does everything the editors do,
  without a display.
- **Extensions**: pure-Python plugins that add panels, map tools, overlays,
  commands, validators and battle templates.
- **The toolkit environment**: one pinned Python environment
  (`toolkit/.venv`), created on first use, with offline installs from wheel
  files.
- **Installers** for Linux (Arch-based, Debian-based, Fedora family), macOS,
  Windows and Haiku (desktop only): devkitPro's GBA toolchain, the desktop
  tools, mGBA and the environment. They have not yet run against the real
  package servers on every system.
- **Prebuilt downloads** of the Studio for Linux x86_64, Windows x64 and
  macOS universal2: one folder each, with Python, Qt and a copy of the
  engine inside.
- Documentation: the [user guide](docs/USER_GUIDE.md); `LICENSE` (MPL-2.0)
  and `THIRD_PARTY_NOTICES.md`.
