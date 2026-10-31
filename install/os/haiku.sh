# Haiku. Sourced by install.sh.
# shellcheck shell=bash
# Desktop only. devkitPro does not publish Haiku builds, so the GBA toolchain
# (devkitARM + libgba + gbafix) is not available yet; see install/SUPPORT.md.
# Haiku runs everything with full rights, so there is no sudo here.

os_plan() {
   [ "${SKIP_DESKTOP:-0}" -eq 1 ] || {
      note "Desktop: 'pkgman install cmd:cmake cmd:python3 cmd:git cmd:pkg_config"
      note "     devel:libsdl2 mgba' from HaikuPorts."
   }
   note "GBA: not available on Haiku yet (devkitPro has no Haiku builds); skipped."
}

os_install() {
   # shellcheck disable=SC2034  # read by finish() in common.sh
   SKIP_GBA=1
   # shellcheck disable=SC2034  # read by verify_desktop() in common.sh
   TOOLKIT_CORE_ONLY=1
   if [ "${SKIP_DESKTOP:-0}" -ne 1 ]; then
      say "Desktop dependencies (pkgman)"
      local yes=()
      [ "$ASSUME_YES" -eq 1 ] && yes=(-y)
      run pkgman install ${yes[@]+"${yes[@]}"} cmd:cmake cmd:python3 cmd:git cmd:pkg_config devel:libsdl2 mgba \
         || die "pkgman could not install the desktop dependencies"
   fi
}
