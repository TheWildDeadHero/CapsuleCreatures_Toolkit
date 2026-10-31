# How this bundle was made

The bundle was packed with PyInstaller (https://pyinstaller.org, version pinned in the toolkit's
`toolkit/packaging/requirements-bundle.txt`). The small start-up program at the front of each executable is
PyInstaller's bootloader, licensed under the GNU GPL version 2 or later with an exception that allows it to be used
in programs under any licence, so it places no conditions on this bundle. PyInstaller's own source:
https://github.com/pyinstaller/pyinstaller.

The Python runtime inside is CPython (https://www.python.org), under the Python Software Foundation License:
`PYTHON-LICENSE.txt` beside this file.
