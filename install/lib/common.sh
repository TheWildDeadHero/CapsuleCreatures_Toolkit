# Shared helpers for the capsule-studio installers. Sourced, not run.
# shellcheck shell=bash

DRY_RUN="${DRY_RUN:-0}"
ASSUME_YES="${ASSUME_YES:-0}"
DEVKITPRO_DIR="${DEVKITPRO_DIR:-/opt/devkitpro}"   # overridable for testing

readonly DKP_KEY="BC26F752D25B92CE272E0F44F7FD5492264BB9D0"
readonly DKP_KEYSERVER="keyserver.ubuntu.com"
readonly DKP_KEYRING_URL="https://pkg.devkitpro.org/devkitpro-keyring.pkg.tar.zst"
# File mode of the temporary pacman.conf (rw-r--r--: readable by pacman under sudo).
readonly DKP_CONF_MODE=644

say()  { printf '\033[1m==> %s\033[0m\n' "$*"; }
note() { printf '    %s\n' "$*"; }
skip() { printf '    %s (already done)\n' "$*"; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# Runs a command, or prints it in --dry-run mode.
run() {
   if [ "$DRY_RUN" -eq 1 ]; then
      printf '    [dry-run] %s\n' "$*"
   else
      "$@"
   fi
}

confirm() {
   [ "$ASSUME_YES" -eq 1 ] && return 0
   [ "$DRY_RUN" -eq 1 ] && return 0
   local reply
   read -r -p "$1 [y/N] " reply
   [[ "$reply" =~ ^[Yy]$ ]]
}

# --- devkitPro pacman repositories (Arch-based and Fedora) --------------------
# Follows https://devkitpro.org/wiki/devkitPro_pacman

dkp_linux_repo() {
   # shellcheck disable=SC2016  # $arch is for pacman to expand, not the shell
   if ldd --version 2>&1 | grep -qi musl; then
      printf '[dkp-linux-musl]\nServer = https://pkg.devkitpro.org/packages/linux-musl/$arch/\n'
   else
      printf '[dkp-linux]\nServer = https://pkg.devkitpro.org/packages/linux/$arch/\n'
   fi
}

dkp_repo_block() {
   printf '[dkp-libs]\nServer = https://pkg.devkitpro.org/packages\n\n'
   dkp_linux_repo
}

# Key, keyring package and repository entries. $1 = pacman.conf path.
dkp_setup_repos() {
   local conf="$1"
   say "devkitPro package signing key"
   if sudo pacman-key --list-keys "$DKP_KEY" >/dev/null 2>&1; then
      skip "key $DKP_KEY present"
   else
      run sudo pacman-key --recv "$DKP_KEY" --keyserver "$DKP_KEYSERVER"
      run sudo pacman-key --lsign "$DKP_KEY"
   fi

   say "devkitPro keyring package"
   if pacman -Q devkitpro-keyring >/dev/null 2>&1; then
      skip "devkitpro-keyring installed"
   else
      run sudo pacman -U --noconfirm "$DKP_KEYRING_URL" || pacman_failed "could not install devkitpro-keyring"
      run sudo pacman-key --populate devkitpro   # devkitPro's documented fix if the hook could not run
   fi

   say "devkitPro repositories in $conf"
   if grep -q '^\[dkp-libs\]' "$conf"; then
      skip "[dkp-libs] present"
   else
      local backup block
      backup="$conf.bak-$(date +%Y%m%d-%H%M%S)"
      block="$(printf '\n# devkitPro (added by capsule-studio, see https://devkitpro.org/wiki/devkitPro_pacman)\n%s' "$(dkp_repo_block)")"
      note "backing up to $backup and appending:"
      printf '%s\n' "$block" | sed 's/^/      /'
      run sudo cp "$conf" "$backup"
      if [ "$DRY_RUN" -eq 0 ]; then
         printf '%s\n' "$block" | sudo tee -a "$conf" >/dev/null
      fi
   fi
}

# Refreshes only devkitPro's databases (never the system's), then installs gba-dev.
# $1 = pacman.conf path whose [options] are reused.
dkp_sync_and_install() {
   local conf="$1"
   say "Sync devkitPro's package databases only"
   local tmp="/tmp/capsule-studio-dkp.conf"
   [ "$DRY_RUN" -eq 1 ] || tmp="$(mktemp)"
   if [ "$DRY_RUN" -eq 0 ]; then
      {
         awk '/^\[/ { in_options = ($0 == "[options]") } in_options' "$conf"
         printf '\n'
         dkp_repo_block
      } > "$tmp"
      chmod "$DKP_CONF_MODE" "$tmp"
   fi
   if ! run sudo pacman --config "$tmp" -Sy; then
      rm -f "$tmp"
      pacman_failed "could not sync devkitPro's package databases"
   fi
   [ "$DRY_RUN" -eq 1 ] || rm -f "$tmp"

   say "Install gba-dev (devkitARM, libgba, gbafix)"
   local flags=(-S --needed)
   [ "$ASSUME_YES" -eq 1 ] && flags+=(--noconfirm)
   run sudo pacman "${flags[@]}" gba-dev || pacman_failed "could not install gba-dev"
}

# Stops with advice. A full system upgrade is only ever suggested, never run.
pacman_failed() {
   cat >&2 <<MSG
error: $1.

If the output above shows downloads failing (404 / "failed retrieving file"),
or a dependency that cannot be satisfied, your package databases are probably
out of date relative to the mirrors, or a package needs newer system packages.
The usual fix on Arch-based systems is a full system upgrade, which you run
yourself:

    sudo pacman -Syu

then re-run this installer. If the error mentions keys or signatures instead,
run 'sudo pacman-key --populate devkitpro' and re-run.
MSG
   exit 1
}

# --- Toolkit Python environment ---------------------------------------------------
# One virtual environment for every capsule-studio tool, in .venv/ at the
# repository root, managed by toolkit/env.py. Haiku has no PySide6 builds, so it
# gets the headless tools only.

STUDIO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

toolkit_args() {   # $1 = os
   if [ "$1" = haiku ]; then echo "--core-only"; fi
}

toolkit_plan() {   # $1 = os
   note "Toolkit: create $STUDIO_ROOT/.venv and install the editors' pinned Python packages"
   note "     (toolkit/requirements/) into it; nothing is installed system-wide."
   [ "$1" != haiku ] || note "     Haiku: command-line tools only (no PySide6 for Haiku, so no editor window)."
}

toolkit_setup() {   # $1 = os
   say "Toolkit Python environment (.venv in this repository)"
   local py
   py="$(command -v python3 || true)"
   [ -n "$py" ] || [ "$DRY_RUN" -eq 1 ] || die "python3 not found after installing the desktop tools"
   # shellcheck disable=SC2046  # toolkit_args prints zero or one word
   run "${py:-python3}" "$STUDIO_ROOT/toolkit/env.py" setup $(toolkit_args "$1") \
      || die "the toolkit environment could not be set up (see above); the launchers retry on first use"
}

toolkit_present() {
   python3 "$STUDIO_ROOT/toolkit/env.py" status --check
}

# --- Verification ---------------------------------------------------------------

VERIFY_FAILED=0
check() {   # check <label> <command...>
   local label="$1"; shift
   if "$@" >/dev/null 2>&1; then
      note "ok       $label"
   else
      note "MISSING  $label"
      VERIFY_FAILED=1
   fi
}

verify_gba() {
   say "Verify GBA toolchain"
   local cxx="$DEVKITPRO_DIR/devkitARM/bin/arm-none-eabi-g++"
   check "devkitARM ($cxx)" test -x "$cxx"
   check "libgba" test -e "$DEVKITPRO_DIR/libgba/lib/libgba.a"
   check "gbafix" test -e "$DEVKITPRO_DIR/tools/bin/gbafix"
   if [ -x "$cxx" ]; then
      local tmp
      tmp="$(mktemp -d)"
      printf '#include <concepts>\nconsteval int f() { return 1; }\nint main() { return f() - 1; }\n' > "$tmp/t.cpp"
      check "C++20 for arm7tdmi" "$cxx" -std=c++20 -mthumb -mcpu=arm7tdmi -c "$tmp/t.cpp" -o "$tmp/t.o"
      rm -rf "$tmp"
   fi
}

verify_desktop() {
   say "Verify desktop toolchain"
   check "C++ compiler" cxx_present
   check "make" have make
   check "cmake" have cmake
   check "python3" have python3
   check "git" have git
   check "SDL2 development files" sdl2_present
   check "mGBA" mgba_present
   if [ "${TOOLKIT_CORE_ONLY:-0}" -eq 1 ]; then
      check "toolkit environment (command-line tools)" python3 "$STUDIO_ROOT/toolkit/env.py" status --check --core-only
   else
      check "toolkit environment (.venv, editors)" toolkit_present
   fi
}

sdl2_present() {
   pkg-config --exists sdl2 2>/dev/null || have sdl2-config
}

mgba_present() {
   have mgba-qt || have mgba || [ -d "/Applications/mGBA.app" ]
}

finish() {
   if [ "$DRY_RUN" -eq 1 ]; then
      say "Dry run finished; nothing was changed"
      return
   fi
   [ "${SKIP_GBA:-0}" -eq 1 ] || verify_gba
   [ "${SKIP_DESKTOP:-0}" -eq 1 ] || verify_desktop
   [ "$VERIFY_FAILED" -eq 0 ] || die "some components are missing (see above)"
   say "Ready. The engine's GBA makefile defaults to $DEVKITPRO_DIR; no environment setup is required."
}

cxx_present() { have c++ || have g++ || have clang++; }
