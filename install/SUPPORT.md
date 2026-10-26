# Installer support

What `install/install.sh` (Linux, macOS, Haiku) and `install/install.ps1`
(Windows) set up on each operating system, and how far each path has been
checked. "GBA" means devkitARM + libgba + gbafix (devkitPro's `gba-dev`).
"Desktop" means a C++ compiler, make, CMake, Python 3, git, SDL2 development
files and mGBA, plus the toolkit environment: `.venv/` in this repository with
the editors' pinned Python packages (see the main README). On Windows that
environment uses python.org's Python 3.12 from winget, because MSYS2's Python
can't load PySide6; on Haiku it holds the command-line tools only, as there
are no PySide6 builds for Haiku.

| OS | Installer | GBA toolchain from | Desktop tools from | Checked so far |
|---|---|---|---|---|
| Arch-based (Arch, CachyOS, EndeavourOS, Manjaro) | `install.sh` | devkitPro's pacman repos, synced on their own | official repos, current databases | lint; mocked run of every step |
| Debian-based (Debian, Ubuntu, Mint, Pop!_OS) | `install.sh` | devkitPro's official `install-devkitpro-pacman` + `dkp-pacman` | apt | lint; mocked run |
| Fedora / RHEL family | `install.sh` | Fedora's `pacman` + devkitPro's repos | dnf | lint; mocked run |
| macOS (Intel, Apple Silicon) | `install.sh` | devkitPro's pacman `.pkg` + `dkp-pacman` | Homebrew (must be installed first) | lint; mocked run; formula names checked against Homebrew |
| Windows 10/11 | `install.ps1` | devkitPro's graphical installer (tick "GBA Development"), mounted into MSYS2 as `/opt/devkitpro` | winget (Git, MSYS2, mGBA) + MSYS2 UCRT64 packages | parsed and dry-run in PowerShell 7; winget IDs checked against winget-pkgs |
| Haiku | `install.sh` | **not available** | HaikuPorts via pkgman | lint; mocked run; recipes checked in HaikuPorts |
| ReactOS | none | **not supported** | **not supported** | see below |
| Redox OS | none | **not supported** | **not supported** | see below |

None of these have run against the real package servers yet. "Mocked run"
means every command was executed in order against stand-in package managers
that record their calls, including re-runs, cancellation and failure paths.

## Rules every installer follows

- Shows its plan and asks before changing anything (`--yes` / `-Yes` to skip).
- `--dry-run` / `-DryRun` prints every command without running it.
- Safe to re-run: finished steps are skipped.
- Never upgrades the rest of the system. On Arch-based systems only
  devkitPro's package databases are synced; if pacman then can't fetch a
  package or satisfy a dependency, the installer stops and suggests
  `sudo pacman -Syu` for you to run. MSYS2 gets the same treatment.
- Edits to system files (`/etc/pacman.conf`, MSYS2's `fstab`) are backed up first.
- Ends by verifying each component, including a C++20 test compile for the GBA.

## Not supported yet, and why

**Haiku (GBA).** devkitPro publishes no Haiku builds. HaikuPorts does have
`arm_none_eabi_gcc`, so a GBA path is possible: it would also need devkitARM's
startup files (`devkitPro/devkitarm-crtls`), libgba and gbafix built from
source on top of that compiler.

**ReactOS.** The Windows installer relies on winget and Windows PowerShell 5.1,
which ReactOS doesn't provide, and MSYS2 has a history of failing to install
on ReactOS (ReactOS issue CORE-10459, marked fixed but not confirmed working).
Worth revisiting as ReactOS matures.

**Redox OS.** Redox lists GCC, make, git, Python and SDL2 apps as working, but
not CMake, and doesn't confirm a native C++ compiler (g++). There is no
devkitARM for Redox. Worth revisiting.

## Known gaps

- Windows: the engine's CMake presets don't name a generator. If CMake in
  MSYS2 picks one that isn't Ninja or MinGW Makefiles, pass `-G Ninja`.
- macOS: devkitPro recommends a reboot after its `.pkg` installs so its
  environment variables are set. The engine's makefile doesn't need them.
