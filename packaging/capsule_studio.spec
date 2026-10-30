# -*- mode: python -*-
# PyInstaller spec of the prebuilt studio bundle (D-40 RI). build_bundle.py runs it; see packaging/README.md.
#
# One-folder bundle: the Python runtime, PySide6 and the Qt libraries stay separate shared libraries next to the
# executables (LGPL-3: the user can replace them), nothing is packed into a single file. Two executables share the
# folder: `studio` (windowed on Windows, the macOS app's main program) and `capsule-studio` (console). The studio's
# own Python sources and the engine files it reads are copied in as plain files (data), not frozen; the analysis
# below still reads them so every standard-library module they import is collected.
#
# Inputs (environment, set by build_bundle.py):
#   CAPSULE_BUNDLE_STAGE    the staged folder: toolkit/, engine/, notices/, bundle_tools.json
#   CAPSULE_BUNDLE_ICONS    the icons folder from make_icons.py
#   CAPSULE_BUNDLE_VERSION  the release version (D-10 YYYY.MM.DD.MMMM)
#   CAPSULE_BUNDLE_ARCH     macOS only: the target architecture (universal2)
import os
import re
import sys
from pathlib import Path

## This folder (toolkit/packaging); SPECPATH is set by PyInstaller.
HERE = Path(SPECPATH)
## The staged data (build_bundle.py stage()).
STAGE = Path(os.environ["CAPSULE_BUNDLE_STAGE"])
## Icons drawn by make_icons.py.
ICONS = Path(os.environ["CAPSULE_BUNDLE_ICONS"])
## The release version.
VERSION = os.environ["CAPSULE_BUNDLE_VERSION"]
## macOS target architecture, or None elsewhere.
TARGET_ARCH = os.environ.get("CAPSULE_BUNDLE_ARCH") or None
## Fields of the version macOS shows (CFBundleShortVersionString takes at most three numbers).
MAC_VERSION_FIELDS = 3

## The studio's sources and the folders their imports start from.
EDITOR = STAGE / "toolkit" / "editor"
## The studio's own extensions: each folder is an import root of its own (plugins/loader.py).
EXTENSIONS = EDITOR / "capsule_studio" / "extensions"
## The engine's Python tools (core/engine.py and core/audio.py put these folders on sys.path).
ENGINE_TOOL_ROOTS = [STAGE / "engine" / "tools", STAGE / "engine" / "tools" / "audio"]
## Folders inside the engine's tools/ that hold no importable code.
ENGINE_TOOL_SKIP = {"ci", "dreamcast", "setup", "audio", "__pycache__"}

## Python modules the bundle never carries: Qt modules the studio does not import (CHECKLIST section 5: only
## QtCore, QtGui and QtWidgets; QtMultimedia is optional and left out, so audio plays in the system's player),
## the Tk GUI toolkit, and readline (it links GNU readline, GPL; nothing in the studio needs line editing).
EXCLUDES = [
   "tkinter", "_tkinter", "readline",
   "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick",
   "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2", "PySide6.QtSvg", "PySide6.QtSvgWidgets", "PySide6.QtSql",
   "PySide6.QtTest", "PySide6.QtXml", "PySide6.QtHelp", "PySide6.QtUiTools", "PySide6.QtConcurrent",
   "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPrintSupport", "PySide6.QtDBus", "PySide6.QtPdf",
   "PySide6.QtPdfWidgets", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtCharts",
   "PySide6.QtDesigner",
]
## Collected files dropped after the analysis (path fragments, '/'-separated): Qt's translations (the studio is in
## English); the SVG image and icon plugins with the SVG library they load (the studio draws no SVG); the GTK
## theme plugin (it would pull the build machine's whole GTK stack in; the portal theme stays); Qt's embedded and
## remote platforms (EGLFS, VNC, LinuxFB, KMS and their input plugins, which also pull Qt Network in).
DROPPED = ("/translations/", "imageformats/libqsvg", "imageformats/qsvg", "iconengines/libqsvgicon",
           "iconengines/qsvgicon", "Qt6Svg", "QtSvg.framework", "platformthemes/libqgtk3",
           "/egldeviceintegrations/", "/plugins/generic/", "libQt6EglF", "Qt6Network", "QtNetwork.framework",
           "platforms/libqeglfs", "platforms/libqvnc", "platforms/libqlinuxfb", "platforms/libqminimalegl",
           "platforms/libqvkkhrdisplay", "platforms/qdirect2d")
## Linux only: libraries of the user's own system that a bundle must not carry, by file name. PyInstaller copies
## every library the Qt plugins link, but the PySide6 wheels themselves rely on the system for these (the
## graphics and desktop stack, fonts, D-Bus, the C++ runtime): a copy from the build machine can clash with the
## user's drivers and newer system libraries. GNU readline (GPL) is never shipped.
LINUX_SYSTEM_LIBS = re.compile(
   r"lib(X[a-zA-Z0-9]*|X11-xcb|xcb.*|xkbcommon.*|wayland-.*|fontconfig|freetype|harfbuzz|png16|jpeg|glib-2\.0|gio-2\.0|"
   r"gobject-2\.0|gmodule-2\.0|gthread-2\.0|dbus-1|systemd|udev|gtk-3|gdk.*|pango.*|cairo.*|atk.*|atspi|epoxy|"
   r"pixman-1|thai|datrie|graphite2|fribidi|selinux|mount|blkid|gcrypt|gpg-error|cap|bsd|md|lz4|zstd|pcre2-8|"
   r"brotli.*|krb5.*|k5crypto|gssapi.*|keyutils|com_err|stdc\+\+|gcc_s|readline|tinfo|ncursesw?|drm|gbm|"
   r"EGL|GL.*|OpenGL)\.so.*")


def modules_under(root: Path, skip: set[str] = frozenset()) -> tuple[list[str], set[str]]:
   """!Every module importable from one import root (top-level .py files and packages).
   @param root  the folder on sys.path
   @param skip  sub-folder names to leave out
   @return (module names, top-level names)
   """
   names, tops = [], set()
   for f in sorted(root.iterdir()):
      if f.suffix == ".py":
         names.append(f.stem)
         tops.add(f.stem)
      elif f.is_dir() and f.name not in skip and (f / "__init__.py").is_file():
         tops.add(f.name)
         for g in sorted(f.rglob("*.py")):
            parts = list(g.relative_to(root).with_suffix("").parts)
            if parts[-1] == "__init__":
               parts.pop()
            names.append(".".join(parts))
   return names, tops


roots = [EDITOR] + sorted(p for p in EXTENSIONS.iterdir() if (p / "plugin.json").is_file())
hidden, own = [], set()
for r in roots:
   n, t = modules_under(r)
   hidden += n
   own |= t
for r in ENGINE_TOOL_ROOTS:
   n, t = modules_under(r, ENGINE_TOOL_SKIP)
   hidden += n
   own |= t

a = Analysis(
   [str(HERE / "bundle_main.py")],
   pathex=[str(HERE), *[str(r) for r in roots], *[str(r) for r in ENGINE_TOOL_ROOTS]],
   hiddenimports=hidden + ["bundle_smoke"],
   excludes=EXCLUDES,
   datas=[(str(STAGE / "toolkit"), "toolkit"), (str(STAGE / "engine"), "engine"),
          (str(STAGE / "notices"), "notices"), (str(STAGE / "bundle_tools.json"), ".")],
   noarchive=False,
)
# The studio's and the engine's modules run from the copied source files (data above), never from the archive.
a.pure = [entry for entry in a.pure if entry[0].split(".")[0] not in own]


def kept(entry: tuple) -> bool:
   """!Whether a collected file stays in the bundle (DROPPED, LINUX_SYSTEM_LIBS).
   @param entry  (destination, source, kind)
   @return bool
   """
   dest = "/" + str(entry[0]).replace("\\", "/")
   if sys.platform.startswith("linux") and LINUX_SYSTEM_LIBS.fullmatch(dest.rsplit("/", 1)[-1]):
      return False
   return not any(d in dest for d in DROPPED)


a.binaries = [e for e in a.binaries if kept(e)]
a.datas = [e for e in a.datas if kept(e)]

pyz = PYZ(a.pure)
# Linux executables carry no icon (the download has capsule-studio.png and add-to-menu.sh instead).
icon = {"win32": str(ICONS / "capsule-studio.ico"), "darwin": str(ICONS / "capsule-studio.icns")}.get(sys.platform)
common = dict(exclude_binaries=True, debug=False, strip=False, upx=False, target_arch=TARGET_ARCH,
              codesign_identity=None, entitlements_file=None, icon=icon)
# The windowed program comes first: the macOS app takes the first executable as its main program.
gui = EXE(pyz, a.scripts, [], name="studio", console=False, **common)
cli = EXE(pyz, a.scripts, [], name="capsule-studio", console=True, **common)
coll = COLLECT(gui, cli, a.binaries, a.datas, strip=False, upx=False, name="capsule-studio")

if sys.platform == "darwin":
   short = ".".join(VERSION.split(".")[:MAC_VERSION_FIELDS])
   app = BUNDLE(
      coll,
      name="CapsuleStudio.app",
      icon=icon,
      bundle_identifier="io.github.thewilddeadhero.capsule-studio",
      version=short,
      info_plist={
         "CFBundleName": "CapsuleCreatures Studio",
         "CFBundleDisplayName": "CapsuleCreatures Studio",
         "CFBundleShortVersionString": short,
         "CFBundleVersion": short,
         "CapsuleReleaseVersion": VERSION,
         "NSHighResolutionCapable": True,
      },
   )
