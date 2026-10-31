# Qt and PySide6 in this bundle (GNU LGPL version 3)

The CapsuleCreatures Studio bundle uses **Qt 6** and **PySide6** (Qt for Python, with its Shiboken6 runtime), both
by The Qt Company, under the GNU Lesser General Public License version 3. The texts are in `qt/licenses/`:
`LGPL-3.0-only.txt` and the GNU GPL version 3 it builds on, `GPL-3.0-only.txt`. PySide6 is also offered under the
GPL version 2 or 3 (`GPL-2.0-only.txt`). The versions are the ones pinned in the toolkit's
`toolkit/requirements/ui.txt` (6.11.2 for the first release); the third-party parts compiled into Qt are listed in
`qt/QT_ATTRIBUTIONS.md`.

The studio itself (its Python sources are in the bundle, in the `toolkit` folder next to the Qt libraries) is
licensed under the Mozilla Public License 2.0, a separate work that uses these libraries.

## Getting the source

- Qt 6.11.2: https://download.qt.io/official_releases/qt/6.11/6.11.2/ (the `single/` folder holds the whole
  source), or the Git repositories at https://code.qt.io/ (mirrored at https://github.com/qt/, tag `v6.11.2`).
- PySide6 and Shiboken6 6.11.2: https://code.qt.io/cgit/pyside/pyside-setup.git/ (tag `v6.11.2`), and the source
  archives under https://download.qt.io/official_releases/QtForPython/.

The bundle uses the libraries exactly as the PySide6 6.11.2 wheels on PyPI ship them (`PySide6-Essentials`,
`shiboken6`); nothing in them was changed.

## Replacing the libraries

The bundle is a plain folder: every Qt and PySide6 library is a separate shared library file, loaded at start-up,
so you can replace any of them with your own build (for instance one you changed and compiled from the source
above). Use a build of the same Qt minor version (6.11), configured like the official one, or the studio may not
start. Where the files are:

| System | Qt libraries | Qt plugins | PySide6 modules |
|---|---|---|---|
| Linux | `_internal/libQt6*.so.6` | `_internal/PySide6/Qt/plugins/` | `_internal/PySide6/*.abi3.so`, `_internal/libpyside6*`, `_internal/libshiboken6*` |
| Windows | `_internal\PySide6\Qt6*.dll` | `_internal\PySide6\plugins\` | `_internal\PySide6\*.pyd`, `pyside6*.dll`, `_internal\shiboken6\` |
| macOS | `CapsuleStudio.app/Contents/Frameworks/PySide6/Qt/lib/Qt*.framework` | `.../PySide6/Qt/plugins/` | `.../PySide6/*.abi3.so`, `libpyside6*`, `shiboken6/` |

If a file is not exactly there, search the folder for its name (for example `libQt6Core.so.6`, `Qt6Core.dll` or
`QtCore.framework`): the packaging tool decides the sub-folders, and the file names stay Qt's own.

1. Quit the studio.
2. Copy your library over the one in the bundle, keeping its file name.
3. macOS only: the app's ad-hoc code signature no longer matches; sign it again ad hoc with
   `codesign --force --deep --sign - CapsuleStudio.app` (no certificate needed).
4. Start the studio. The environment variables `QT_PLUGIN_PATH` and `QT_DEBUG_PLUGINS=1` help when a replaced
   plugin does not load.

You may also rebuild the whole bundle with your own Qt: the build is `toolkit/packaging/build_bundle.py` in the
CapsuleCreatures toolkit's source, which takes whatever PySide6 is installed in the Python that runs it. Nothing in
the studio's licence or in this bundle forbids modifying these libraries or reverse engineering them to debug such
modifications.
