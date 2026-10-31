# CapsuleCreatures Studio (prebuilt bundle)

This folder is the CapsuleCreatures Studio, ready to run: every editor of the toolkit, the Python runtime and Qt are
inside, so nothing needs to be installed to open and edit a game. It is one folder: keep its files together, and
move or delete the whole folder to move or remove the studio.

## Starting it

| System | Start the Studio | Other editors |
|---|---|---|
| Linux (x86_64) | double-click `studio` in your file manager, or run `./studio`; `./add-to-menu.sh` adds it to your application menu | `map-editor`, `battle-editor`, ... beside it |
| Windows (x64) | double-click `studio.exe` | `map-editor.cmd`, `battle-editor.cmd`, ... beside it |
| macOS (Apple silicon and Intel) | double-click `CapsuleStudio.app` (drag it to Applications first if you like) | `CapsuleStudio.app/Contents/MacOS/studio map-editor` |

The bundles are **not code-signed**, so the system warns the first time:
- macOS: the app "cannot be opened because the developer cannot be verified". Open **System Settings > Privacy &
  Security**, scroll to the message about CapsuleStudio and choose **Open Anyway** (once). On older systems,
  right-click the app and choose **Open**.
- Windows: SmartScreen shows "Windows protected your PC". Choose **More info**, then **Run anyway** (once).

Linux needs glibc 2.34 or newer (Ubuntu 22.04, Debian 12, Fedora 35, RHEL / AlmaLinux / Rocky Linux 9, current
Arch-based systems). On an X11 desktop Qt also needs the system's `xcb-util-cursor` library (`xcb-util-cursor` on
Arch and Fedora, `libxcb-cursor0` on Debian and Ubuntu); Wayland desktops need nothing extra.

The command line is the `capsule-studio` program (`capsule-studio.exe`; on macOS
`CapsuleStudio.app/Contents/MacOS/capsule-studio`): `capsule-studio --help`, `capsule-studio template list`,
`capsule-studio new MyGame --template starter`, and so on.

## What works out of the box

- **New games from a template**: **New game...** on the Studio's start window (or **Studio > New game...**), with the engine's **Starter** sample (a complete
  neutral battle game to copy) or **Blank**.
- **Opening and editing a game**: worlds, maps and tilesets, encounters, events, objects and locations, assets
  (sprites, text, text boxes, menus, screens), scripts, battle data with its structure and logic, project settings
  and the code page, and audio manifests.
- **Previews that match the build**: palettes, tiles, fonts and text are drawn with the engine's own compilers,
  which the bundle carries (the engine's Python tools, headers, assets and samples, in `engine/` inside the bundle).
- **The command line**: every `capsule-studio` command.
- **Audio**: Play hands the sound to your system's player (Qt Multimedia is not bundled).

## What needs the toolchain installer

Building and running a game needs compilers the bundle does not carry. Clone the CapsuleCreatures repository with
its submodules and run its installer (`./setup`, or `setup.cmd` on Windows); it installs devkitPro's devkitARM, CMake,
a C/C++ compiler, SDL2's dependencies and mGBA. Then:

- **Building for GBA** (`./build gba-release`) and running the `.gba` file in mGBA;
- **Building for the desktop** (`./build desktop-release`);
- **The battle bench** and **audio rendering** in the editors, which compile parts of the engine with CMake;
- **GBA memory reports** from a build folder (they read the build's ELF file with devkitARM's tools).

To edit a game with the bundle while building it from a checkout, point the bundle at the checkout's engine: set
the environment variable `CAPSULE_ENGINE` to the checkout's `engine` folder before starting the studio. Without it
the bundle uses its own copy of the engine, which matches the release.

## Licences

- The studio and the engine: Mozilla Public License 2.0 (`LICENSE`).
- Qt 6 and PySide6 are used under the GNU LGPL version 3. They are separate shared libraries in this folder, and you
  may replace them with your own build: `notices/QT_LGPL_NOTICE.md` says where they are, how to replace them and
  where to get their source.
- Third-party parts inside Qt: `notices/qt/QT_ATTRIBUTIONS.md`, with every licence text in `notices/qt/licenses/`.
- The Python runtime: `notices/PYTHON-LICENSE.txt`. The bundle was made with PyInstaller: `notices/PYINSTALLER.md`.
- The project's own third-party notices, when present: `THIRD_PARTY_NOTICES*` beside this file.

`VERSION.txt` names the release and the commits this bundle was built from.
