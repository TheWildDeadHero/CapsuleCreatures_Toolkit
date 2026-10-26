# macOS (Intel and Apple Silicon). Sourced by install.sh.
# shellcheck shell=bash
# GBA: devkitPro's pacman .pkg installer (github.com/devkitPro/pacman releases),
# then dkp-pacman, which manages only devkitPro's packages. Desktop: Homebrew.

readonly DKP_MAC_PKG_URL="https://github.com/devkitPro/pacman/releases/latest/download/devkitpro-pacman-installer.pkg"

os_plan() {
   [ "${SKIP_DESKTOP:-0}" -eq 1 ] || {
      note "Desktop: Xcode command line tools (if missing), then"
      note "     'brew install cmake sdl2-compat python git pkgconf mgba'. Homebrew must"
      note "     already be installed (https://brew.sh); this script won't install it."
   }
   [ "${SKIP_GBA:-0}" -eq 1 ] || {
      note "GBA: devkitPro's pacman .pkg installer (if missing), then"
      note "     'sudo dkp-pacman -Sy --needed gba-dev'."
   }
}

dkp_pacman_cmd() {
   if have dkp-pacman; then echo dkp-pacman
   elif [ -x "$DEVKITPRO_DIR/pacman/bin/pacman" ]; then echo "$DEVKITPRO_DIR/pacman/bin/pacman"
   fi
}

os_install() {
   if [ "${SKIP_DESKTOP:-0}" -ne 1 ]; then
      say "Xcode command line tools"
      if xcode-select -p >/dev/null 2>&1; then
         skip "installed"
      else
         run xcode-select --install
         die "finish the Xcode command line tools install that just opened, then re-run"
      fi
      say "Desktop dependencies (Homebrew)"
      have brew || die "Homebrew is required: install it from https://brew.sh, then re-run"
      run brew install cmake sdl2-compat python git pkgconf mgba || die "brew could not install the desktop dependencies"
   fi
   if [ "${SKIP_GBA:-0}" -ne 1 ]; then
      say "devkitPro pacman"
      local dkp
      dkp="$(dkp_pacman_cmd)"
      if [ -n "$dkp" ]; then
         skip "$dkp present"
      else
         local pkg="/tmp/devkitpro-pacman-installer.pkg"
         run curl -fL -o "$pkg" "$DKP_MAC_PKG_URL"
         run sudo installer -pkg "$pkg" -target /
         run rm -f "$pkg"
         dkp="$(dkp_pacman_cmd)"
         [ -n "$dkp" ] || dkp="$DEVKITPRO_DIR/pacman/bin/pacman"
      fi
      say "Install gba-dev (devkitARM, libgba, gbafix)"
      local flags=(-Sy --needed)
      [ "$ASSUME_YES" -eq 1 ] && flags+=(--noconfirm)
      run sudo "$dkp" "${flags[@]}" gba-dev || die "dkp-pacman could not install gba-dev"
      note "devkitPro recommends a reboot (or new login) so its environment variables are set;"
      note "the engine's makefile doesn't need them."
   fi
}
