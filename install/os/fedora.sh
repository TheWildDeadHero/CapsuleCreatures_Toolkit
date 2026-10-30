# Fedora / RHEL family. Sourced by install.sh.
# shellcheck shell=bash
# GBA: Fedora's pacman package with devkitPro's repositories, per
# https://devkitpro.org/wiki/devkitPro_pacman. On Fedora pacman manages only
# devkitPro's packages; dnf keeps managing the system. Desktop: dnf.

PACMAN_CONF="${PACMAN_CONF:-/etc/pacman.conf}"   # overridable for testing

os_plan() {
   [ "${SKIP_DESKTOP:-0}" -eq 1 ] || {
      note "Desktop: 'sudo dnf install gcc-c++ make cmake python3 git pkgconf-pkg-config"
      note "     pkgconfig(sdl2) mgba-qt xcb-util-cursor'."
   }
   [ "${SKIP_GBA:-0}" -eq 1 ] || {
      note "GBA: 'sudo dnf install pacman', initialise its keyring, add devkitPro's key,"
      note "     keyring and repos to $PACMAN_CONF (backed up first), sync only those, then"
      note "     'sudo pacman -S --needed gba-dev'."
   }
}

os_install() {
   if [ "${SKIP_DESKTOP:-0}" -ne 1 ]; then
      say "Desktop dependencies (dnf)"
      local yes=()
      [ "$ASSUME_YES" -eq 1 ] && yes=(-y)
      # xcb-util-cursor: Qt 6's X11 platform plugin needs it for the studio (Wayland sessions do not).
      run sudo dnf install ${yes[@]+"${yes[@]}"} gcc-c++ make cmake python3 git pkgconf-pkg-config 'pkgconfig(sdl2)' mgba-qt \
         xcb-util-cursor \
         || die "dnf could not install the desktop dependencies"
   fi
   if [ "${SKIP_GBA:-0}" -ne 1 ]; then
      say "pacman (for devkitPro's packages only)"
      if have pacman; then
         skip "pacman installed"
      else
         local yes=()
         [ "$ASSUME_YES" -eq 1 ] && yes=(-y)
         run sudo dnf install ${yes[@]+"${yes[@]}"} pacman || die "dnf could not install pacman"
      fi
      if [ -d /etc/pacman.d/gnupg ]; then
         skip "pacman keyring initialised"
      else
         run sudo pacman-key --init
      fi
      dkp_setup_repos "$PACMAN_CONF"
      dkp_sync_and_install "$PACMAN_CONF"
   fi
}
