# Debian-based Linux (Debian, Ubuntu, Mint, Pop!_OS, ...). Sourced by install.sh.
# shellcheck shell=bash
# GBA: devkitPro's official install-devkitpro-pacman script, then dkp-pacman,
# which manages only devkitPro's packages. Desktop: apt.

readonly DKP_DEBIAN_SCRIPT_URL="https://apt.devkitpro.org/install-devkitpro-pacman"

os_plan() {
   [ "${SKIP_GBA:-0}" -eq 1 ] || {
      note "GBA: run devkitPro's official install-devkitpro-pacman script (if dkp-pacman"
      note "     is missing), then 'sudo dkp-pacman -Sy --needed gba-dev'. dkp-pacman only"
      note "     manages devkitPro's packages."
   }
   [ "${SKIP_DESKTOP:-0}" -eq 1 ] || {
      note "Desktop: 'sudo apt-get update' and 'sudo apt-get install build-essential cmake"
      note "     python3 python3-venv git pkg-config libsdl2-dev mgba-qt'. On Ubuntu, mgba-qt is in the"
      note "     'universe' component."
   }
}

os_install() {
   if [ "${SKIP_DESKTOP:-0}" -ne 1 ]; then
      say "Desktop dependencies (apt)"
      local yes=()
      [ "$ASSUME_YES" -eq 1 ] && yes=(-y)
      run sudo apt-get update
      run sudo apt-get install ${yes[@]+"${yes[@]}"} build-essential cmake python3 python3-venv git pkg-config libsdl2-dev mgba-qt \
         || die "apt could not install the desktop dependencies (on Ubuntu, enable 'universe' for mgba-qt)"
   fi
   if [ "${SKIP_GBA:-0}" -ne 1 ]; then
      say "devkitPro pacman (dkp-pacman)"
      if have dkp-pacman; then
         skip "dkp-pacman installed"
      else
         have wget || die "wget is needed: sudo apt-get install wget"
         local script="/tmp/install-devkitpro-pacman"
         [ "$DRY_RUN" -eq 1 ] || script="$(mktemp)"
         run wget -O "$script" "$DKP_DEBIAN_SCRIPT_URL"
         run chmod +x "$script"
         note "devkitPro asks you to inspect this script before running it: $script"
         confirm "Run devkitPro's install-devkitpro-pacman with sudo?" || die "cancelled"
         run sudo "$script"
         run rm -f "$script"
      fi
      say "Install gba-dev (devkitARM, libgba, gbafix)"
      local flags=(-Sy --needed)
      [ "$ASSUME_YES" -eq 1 ] && flags+=(--noconfirm)
      run sudo dkp-pacman "${flags[@]}" gba-dev || die "dkp-pacman could not install gba-dev"
   fi
}
