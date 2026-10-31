# Prebuilt studio bundles (D-40 RI)

This folder makes the prebuilt CapsuleCreatures Studio downloads: one folder per platform with the studio, every
editor, the Python runtime, Qt and the engine files the studio reads, so a user can open and edit a game without
installing anything. The scripted installers (`../install/`) stay the way to get the full toolchain (devkitARM,
CMake, compilers, mGBA) for building games. The umbrella's `.github/workflows/studio-bundles.yml` builds and tests
the bundles for a release.

| File | What |
|---|---|
| `build_bundle.py` | `build`: stage, icons, PyInstaller, layout, archive; `smoke ARCHIVE`: unpack and test like a user |
| `capsule_studio.spec` | the PyInstaller spec: one folder, two executables, what is collected and what is left out |
| `bundle_main.py` | the bundle's entry point: tool names, `python script.py` stand-in, `--bundle-smoke` |
| `bundle_smoke.py` | the smoke test (engine found, Starter game made, extensions load, Studio opens every page) |
| `make_icons.py` | draws the icons from simple shapes at build time (no image is committed) |
| `qt_notices.py` | regenerates `notices/qt/` from a qtbase checkout when the PySide6 pin changes |
| `requirements-bundle.txt` | the pinned build tools (PyInstaller and its dependencies) |
| `notices/` | what ships in `notices/` of every download, and the download's `README.md` (`BUNDLE_README.md`) |
| `linux/add-to-menu.sh` | shipped in the Linux download: adds the studio to the desktop's application menu |

## Choices

- **PyInstaller** (6.22): mature, maintained hooks for PySide6 6.x, builds Linux, Windows and macOS universal2 apps
  from the same spec, and its one-folder mode keeps every Qt library a separate file, which the LGPL-3 needs (the
  user can replace them; `notices/QT_LGPL_NOTICE.md` says how). Its bootloader's licence (GPL with an exception)
  puts no conditions on the bundle. Nuitka and cx_Freeze were the alternatives: Nuitka compiles the studio's code
  (long builds, and the extension loader and the plugin rules need the sources as files); cx_Freeze would work,
  but PyInstaller's PySide6 hooks and macOS app support are the more used and maintained.
- **The studio's code stays source.** `toolkit/editor/capsule_studio` and the engine files are copied in as plain
  files (`_internal/toolkit`, `_internal/engine`; macOS: inside the app's `Resources`). The extension loader, the
  pure-Python plugin rule and `core/engine.py` (it finds `../engine` beside the toolkit) work unchanged. The `.pyc`
  files are compiled at build time (unchecked-hash), and nothing writes into the bundle at run time.
- **The engine is shipped, not asked for.** The bundle carries the engine's tracked files except `tests/`,
  `.github/`, `.vscode/` and `submodules/` (about 11 MB with the compiled `.pyc` files): the Python tools the studio imports, the headers it reads,
  the fonts and the Starter sample. That is all the studio needs to make, open and edit a game. Building a game,
  the battle bench and audio rendering need CMake and compilers, which come with the installers; a user who has
  a checkout can point the bundle at it with `CAPSULE_ENGINE`.
- **Qt modules**: only QtCore, QtGui and QtWidgets (what the studio imports). QtMultimedia is left out (it would add
  Qt's FFmpeg libraries and their notices); Play then uses the system's player, as the studio already does without
  it. Also left out: the SVG plugins, Qt Network and the embedded platforms (EGLFS, VNC, LinuxFB), the GTK theme
  plugin and translations. `build_bundle.py smoke` fails if an unused Qt module is in a download.
- **Linux** relies on the user's system for the desktop stack (X11/XCB or Wayland, fontconfig, GL, D-Bus, the C++
  runtime), exactly as the PySide6 wheels do; copies from the build machine would clash with newer drivers. GNU
  readline (GPL) is never shipped. The build runs in the manylinux_2_34 container with a Python built there from
  CPython's pinned release commit, so the bundle needs glibc 2.34 or newer: the floor the PySide6 6.11 wheels' Qt
  sets (glibc 2.34, GLIBCXX_3.4.29). CI fails the build when any ELF file of the download needs more
  (umbrella `.github/scripts/check_elf_baseline.py`).
  No AppImage: AppImage's tool has no versioned release to pin, an AppImage needs FUSE on the user's machine and
  CI, and replacing a Qt library inside its image is harder than in a folder; the `.tar.gz` folder covers it.
- **Windows**: a zip, no installer (an installer adds a second tool and uninstall logic for a folder that needs
  neither). **macOS**: `CapsuleStudio.app` in a zip made with the system's `zip -y` (symbolic links kept), ad-hoc signed by PyInstaller, not notarized;
  the README says how to open it.

## Building one locally

In the Python that will be bundled (3.10 or later; CI uses 3.14.8), with the umbrella checkout's engine beside the
toolkit:

    python -m pip install --only-binary=:all: -r toolkit/requirements/ui.txt
    python -m pip install -r packaging/requirements-bundle.txt
    python packaging/build_bundle.py build --version 2026.10.31.1200 --work build/bundle-1
    python packaging/build_bundle.py smoke build/bundle-1/out/capsule-studio-2026.10.31.1200-linux-x86_64.tar.gz --work build/bundle-1-smoke

(paths relative to the toolkit; `build/` is ignored by git). `--work` must be a new or empty folder: the build
never deletes anything. `CAPSULE_ENGINE` picks another engine checkout. `--require-licence` (CI) stops when the
toolkit has no `LICENSE`.
