#!/usr/bin/env bash
# capsule-studio installer: everything needed to build and run CapsuleCreatures
# projects for GBA and desktop on this machine.
#
#   GBA:      devkitARM, libgba, gbafix (devkitPro's gba-dev group)
#   Desktop:  C++ compiler, make, CMake, Python 3, git, SDL2 development files, mGBA
#   Toolkit:  the editors' Python environment (.venv in this repository, pinned
#             packages from toolkit/requirements/; nothing system-wide)
#
# Supported here: Arch-based, Debian-based and Fedora-family Linux, macOS, Haiku
# (desktop only). Windows: install/install.ps1. Status of every OS: install/SUPPORT.md.
#
# Run as your normal user; sudo is used only for the steps that need it. It shows
# the plan and asks before changing anything, can be re-run safely, never upgrades
# the rest of your system, and ends by verifying every component.
#
# Usage: install/install.sh [--dry-run] [--yes] [--gba-only | --desktop-only]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=SCRIPTDIR/lib/common.sh
. "$HERE/lib/common.sh"

SKIP_GBA=0
SKIP_DESKTOP=0
for arg in "$@"; do
   case "$arg" in
      --dry-run) DRY_RUN=1 ;;
      --yes) ASSUME_YES=1 ;;
      --gba-only) SKIP_DESKTOP=1 ;;
      --desktop-only) SKIP_GBA=1 ;;
      -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
      *) die "unknown option: $arg (try --help)" ;;
   esac
done
[ "$SKIP_GBA" -eq 1 ] && [ "$SKIP_DESKTOP" -eq 1 ] && die "--gba-only and --desktop-only together leave nothing to do"

OS_RELEASE_FILE="${OS_RELEASE_FILE:-/etc/os-release}"   # overridable for testing
UNAME_S="${UNAME_S:-$(uname -s)}"                       # overridable for testing

detect_os() {
   case "$UNAME_S" in
      Darwin) echo macos; return ;;
      Haiku) echo haiku; return ;;
      Linux) ;;
      *) echo unsupported; return ;;
   esac
   local id="" like=""
   if [ -r "$OS_RELEASE_FILE" ]; then
      # shellcheck disable=SC1090
      id="$(. "$OS_RELEASE_FILE"; echo "${ID:-}")"
      # shellcheck disable=SC1090
      like="$(. "$OS_RELEASE_FILE"; echo "${ID_LIKE:-}")"
   fi
   case " $id $like " in
      *" arch "*) echo arch ;;
      *" fedora "*|*" rhel "*) echo fedora ;;
      *" debian "*|*" ubuntu "*) echo debian ;;
      *) echo unsupported ;;
   esac
}

main() {
   local os
   os="$(detect_os)"
   [ "$os" != unsupported ] || die "this system isn't supported by install.sh yet; see install/SUPPORT.md"
   # Haiku has no separate root user; everywhere else, run unprivileged.
   if [ "$os" != haiku ] && [ "$(id -u)" -eq 0 ]; then
      die "run as your normal user; the installer uses sudo where needed"
   fi
   # shellcheck source=/dev/null
   . "$HERE/os/$os.sh"

   say "Detected: $os"
   os_plan
   [ "$SKIP_DESKTOP" -eq 1 ] || toolkit_plan "$os"
   confirm "Continue?" || die "cancelled, nothing was changed"
   os_install
   [ "$SKIP_DESKTOP" -eq 1 ] || toolkit_setup "$os"
   finish
}

main
