# Arch-based Linux (Arch, CachyOS, EndeavourOS, Manjaro, ...). Sourced by install.sh.
# shellcheck shell=bash
# GBA: devkitPro's own pacman repositories (not the AUR), synced on their own.
# Desktop: official repositories, installed against your current package
# databases. Nothing here upgrades the rest of the system.

PACMAN_CONF="${PACMAN_CONF:-/etc/pacman.conf}"   # overridable for testing

os_plan() {
   [ "${SKIP_GBA:-0}" -eq 1 ] || {
      note "GBA: import devkitPro's signing key, install devkitpro-keyring, add devkitPro's"
      note "     [dkp-libs]/[dkp-linux] repos to $PACMAN_CONF (backed up first), sync only"
      note "     those, then 'sudo pacman -S --needed gba-dev'."
   }
   [ "${SKIP_DESKTOP:-0}" -eq 1 ] || {
      note "Desktop: 'sudo pacman -S --needed base-devel cmake python git pkgconf <sdl2> mgba-qt'"
      note "     from the official repos, using your current package databases."
   }
   note "Nothing else on your system is upgraded."
}

os_install() {
   have pacman || die "pacman not found"
   if [ "${SKIP_GBA:-0}" -ne 1 ]; then
      dkp_setup_repos "$PACMAN_CONF"
      dkp_sync_and_install "$PACMAN_CONF"
   fi
   if [ "${SKIP_DESKTOP:-0}" -ne 1 ]; then
      say "Desktop dependencies (official repositories)"
      # Arch replaced sdl2 with sdl2-compat; older snapshots still ship sdl2.
      local sdl=sdl2-compat
      pacman -Si sdl2-compat >/dev/null 2>&1 || sdl=sdl2
      local flags=(-S --needed)
      [ "$ASSUME_YES" -eq 1 ] && flags+=(--noconfirm)
      run sudo pacman "${flags[@]}" base-devel cmake python git pkgconf "$sdl" mgba-qt \
         || pacman_failed "could not install the desktop dependencies"
   fi
}
