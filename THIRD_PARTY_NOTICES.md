# Third-party notices: CapsuleCreatures Toolkit

The toolkit (the studio, its editors and the installers) is licensed under the
Mozilla Public License 2.0 (`LICENSE`). This file lists the third-party parts
it uses or installs. None of them is vendored in this repository: the Python
packages come from PyPI at the versions pinned in `toolkit/requirements/`, and
the toolchains from their vendors' own package repositories.

| Part | How the toolkit uses it | Licence | Source |
|---|---|---|---|
| Qt 6 (QtCore, QtGui, QtWidgets; optional QtMultimedia) through PySide6-Essentials / shiboken6 6.11.2 | the studio's user interface; installed into `toolkit/.venv` from PyPI, and **bundled** in the prebuilt studio downloads | LGPL-3.0 (Qt and PySide6 are also available under the GPL and commercially) | https://download.qt.io/official_releases/qt/6.11/6.11.2/ and https://download.qt.io/official_releases/QtForPython/ |
| PySide6-Addons 6.11.2 (Qt Multimedia, with Qt's FFmpeg libraries) | optional: audio playback inside the editors | LGPL-3.0; FFmpeg LGPL-2.1 or later | as above; https://ffmpeg.org |
| CPython | runs the toolkit; embedded in the prebuilt studio downloads | Python Software Foundation License | https://www.python.org |
| PyInstaller bootloader (when the prebuilt downloads are made with PyInstaller) | starts the bundled studio | GPL-2.0 with a bootloader exception (no obligation for the bundled program) | https://pyinstaller.org |
| devkitPro (devkitARM, libgba, gbafix) | installed by `install/` from devkitPro's own package repositories or installer | each tool and library under its own licence (libgba: LGPL with a static-linking exception, see the engine's `THIRD_PARTY_NOTICES.md`) | https://devkitpro.org |
| mGBA | installed by `install/` from the operating system's packages to run ROMs; never shipped by the toolkit | MPL-2.0 | https://mgba.io |
| SDL2, CMake, a C++ compiler, Git | installed by `install/` from the operating system's packages for desktop builds; not shipped | their own licences | |

The GBA toolchain the installers set up is devkitPro's: games built with it are
based in part on the work of devkitPro (https://devkitpro.org).

## Qt for Python (PySide6) in the prebuilt studio downloads

The prebuilt studio downloads are one-folder bundles, which keeps them within
the LGPL-3.0's terms. Each download must:

1. keep Qt, PySide6 and shiboken6 as **separate shared libraries** in the
   bundle's folder (never linked statically or packed into one executable), so
   a user can replace them with their own builds of the same version;
2. say how to do that replacement (for example a short README in the bundle's
   notices folder naming the library files and the version they must match);
3. ship the GNU LGPL-3.0 and GNU GPL-3.0 texts and Qt's own attribution notices
   for the modules it carries (and FFmpeg's notice when Qt Multimedia is in it);
4. name where the corresponding sources are: Qt 6.11.2 and PySide6 / shiboken6
   6.11.2 at the download.qt.io links above;
5. impose no terms that forbid reverse engineering for debugging those
   replacements.

Running the toolkit from source (`./studio` with `toolkit/.venv`) installs the
same packages from PyPI under their own licences; nothing is redistributed.
