<#
.SYNOPSIS
   capsule-studio installer for Windows 10/11: everything needed to build and run
   CapsuleCreatures projects for GBA and desktop.

.DESCRIPTION
   GBA:     devkitPro's official installer (github.com/devkitPro/installer); you tick
            "GBA Development" in its window. Its folder is then made visible to MSYS2
            as /opt/devkitpro, where the engine's GBA makefile expects it.
   Desktop: winget installs Git, MSYS2 and mGBA. Inside MSYS2's UCRT64 environment,
            pacman installs GCC, make, CMake, Ninja, Python 3, pkg-config and SDL2.
            Build from the "MSYS2 UCRT64" shell.
   Toolkit: python.org's Python 3.12 (winget; MSYS2's Python can't load PySide6),
            then the editors' Python environment in .venv in this repository, with
            the pinned packages from toolkit\requirements\ (PySide6, and PySide6-Addons
            for playing audio in the editors: optional, without it or without an audio
            device Play uses the system's player). Nothing system-wide.

   Shows the plan and asks before changing anything, can be re-run safely, never
   upgrades MSYS2 as a whole, and ends by verifying every component.
   Works in Windows PowerShell 5.1 and PowerShell 7.

.EXAMPLE
   powershell -ExecutionPolicy Bypass -File install\install.ps1 -DryRun
#>
[CmdletBinding()]
param(
   [switch]$DryRun,
   [switch]$Yes,
   [switch]$GbaOnly,
   [switch]$DesktopOnly,
   [string]$Msys2Root = 'C:\msys64',
   [string]$DevkitProRoot = 'C:\devkitPro'
)

$ErrorActionPreference = 'Stop'
if ($GbaOnly -and $DesktopOnly) { throw '-GbaOnly and -DesktopOnly together leave nothing to do' }
$DoGba = -not $DesktopOnly
$DoDesktop = -not $GbaOnly

$Ucrt64Packages = @(
   'mingw-w64-ucrt-x86_64-gcc', 'mingw-w64-ucrt-x86_64-cmake', 'mingw-w64-ucrt-x86_64-ninja',
   'mingw-w64-ucrt-x86_64-python', 'mingw-w64-ucrt-x86_64-pkgconf', 'mingw-w64-ucrt-x86_64-SDL2', 'make'
)
$WingetPackages = @('Git.Git', 'MSYS2.MSYS2', 'JeffreyPfau.mGBA', 'Python.Python.3.12')
$StudioRoot = Split-Path -Parent $PSScriptRoot
$EnvScript = Join-Path $StudioRoot 'toolkit\env.py'

function Say([string]$Text)  { Write-Host "==> $Text" -ForegroundColor Cyan }
function Note([string]$Text) { Write-Host "    $Text" }
function Skip([string]$Text) { Write-Host "    $Text (already done)" }
function Fail([string]$Text) { Write-Host "error: $Text" -ForegroundColor Red; exit 1 }

# Runs a script block, or prints its description in -DryRun mode.
function Invoke-Step([string]$Description, [scriptblock]$Action) {
   if ($DryRun) { Write-Host "    [dry-run] $Description"; return }
   & $Action
}

function Confirm-Continue([string]$Question) {
   if ($Yes -or $DryRun) { return $true }
   $reply = Read-Host "$Question [y/N]"
   return ($reply -match '^[Yy]$')
}

$Bash = "$Msys2Root\usr\bin\bash.exe"

# Runs a command in MSYS2's UCRT64 environment; returns its exit code only
# (output goes to the console, or nowhere with -Quiet).
function Invoke-Ucrt64([string]$Command, [switch]$Quiet) {
   $env:MSYSTEM = 'UCRT64'
   $env:CHERE_INVOKING = '1'
   if ($Quiet) { & $Bash -lc $Command 2>&1 | Out-Null } else { & $Bash -lc $Command | Out-Host }
   return $LASTEXITCODE
}

# --- Plan -------------------------------------------------------------------------
Say 'Detected: Windows'
if ($DoDesktop) {
   Note "Desktop: winget install $($WingetPackages -join ', ') (skipping any already installed),"
   Note "     then in MSYS2 UCRT64: pacman -S --needed $($Ucrt64Packages -join ' ')"
}
if ($DoGba) {
   Note 'GBA: download and run devkitPro''s installer (tick "GBA Development"), then add'
   Note "     '$($DevkitProRoot.Replace('\','/')) /opt/devkitpro' to $Msys2Root\etc\fstab (backed up first)."
}
if ($DoDesktop) {
   Note "Toolkit: create $StudioRoot\.venv and install the editors' pinned Python packages into it."
   Note "     Audio playback in the editors (PySide6-Addons) is optional: if it can't be installed, Play uses the system's player."
}
Note 'Nothing else is upgraded.'
if (-not (Confirm-Continue 'Continue?')) { Fail 'cancelled, nothing was changed' }

# --- Desktop ------------------------------------------------------------------------
if ($DoDesktop) {
   Say 'Desktop tools (winget)'
   $haveWinget = [bool](Get-Command winget -ErrorAction SilentlyContinue)
   if (-not $haveWinget -and -not $DryRun) {
      Fail 'winget is missing: install "App Installer" from the Microsoft Store, then re-run'
   }
   foreach ($id in $WingetPackages) {
      if ($haveWinget) {
         $listed = winget list --id $id -e --accept-source-agreements 2>$null | Select-String -SimpleMatch $id
         if ($listed) { Skip $id; continue }
      }
      $wingetArgs = @('install', '--id', $id, '-e', '--accept-source-agreements')
      if ($Yes) { $wingetArgs += '--accept-package-agreements' }
      Invoke-Step "winget $($wingetArgs -join ' ')" {
         winget @wingetArgs
         if ($LASTEXITCODE -ne 0) { Fail "winget could not install $id" }
      }
   }

   Say 'Build tools inside MSYS2 (UCRT64)'
   if (-not $DryRun -and -not (Test-Path $Bash)) { Fail "MSYS2 not found at $Msys2Root (use -Msys2Root)" }
   $pacmanCmd = "pacman -S --needed --noconfirm $($Ucrt64Packages -join ' ')"
   Invoke-Step "MSYS2 UCRT64: $pacmanCmd" {
      if ((Invoke-Ucrt64 $pacmanCmd) -ne 0) {
         Note 'pacman could not install everything. If downloads failed or a dependency'
         Note 'could not be met, update MSYS2 yourself from the "MSYS2 UCRT64" shell with'
         Note '    pacman -Syu'
         Note '(it may ask you to close the window and run it again), then re-run this script.'
         Fail 'MSYS2 package install failed'
      }
   }
}

# --- Toolkit environment ------------------------------------------------------------
# The Python launcher (py.exe) comes with python.org's Python; a new install may not
# be on this session's PATH yet, so its usual locations are checked too.
function Find-PyLauncher {
   $cmd = Get-Command py -ErrorAction SilentlyContinue
   if ($cmd) { return $cmd.Source }
   foreach ($p in @("$env:LOCALAPPDATA\Programs\Python\Launcher\py.exe", "$env:SystemRoot\py.exe")) {
      if (Test-Path $p) { return $p }
   }
   return $null
}

if ($DoDesktop) {
   Say 'Toolkit Python environment (.venv in this repository)'
   Invoke-Step "py -3.12 $EnvScript setup" {
      $py = Find-PyLauncher
      if (-not $py) {
         Note 'The Python launcher is not on PATH yet. Open a new terminal and run scene-editor.cmd;'
         Note 'it sets the environment up on first use.'
      } else {
         & $py -3.12 $EnvScript setup | Out-Host
         if ($LASTEXITCODE -ne 0) { Fail 'the toolkit environment could not be set up (see above); scene-editor.cmd retries on first use' }
      }
   }
}

# --- GBA ----------------------------------------------------------------------------
if ($DoGba) {
   Say 'devkitPro (devkitARM, libgba, gbafix)'
   $gxx = "$DevkitProRoot\devkitARM\bin\arm-none-eabi-g++.exe"
   if (Test-Path $gxx) {
      Skip "devkitARM found in $DevkitProRoot"
   } else {
      Invoke-Step 'download devkitPro''s latest installer from github.com/devkitPro/installer and run it' {
         $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/devkitPro/installer/releases/latest' `
                                      -Headers @{ 'User-Agent' = 'capsule-studio' }
         $asset = $release.assets | Where-Object { $_.name -like '*.exe' } | Select-Object -First 1
         if (-not $asset) { Fail 'no installer found in devkitPro''s latest release' }
         $exe = Join-Path $env:TEMP $asset.name
         Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $exe -UseBasicParsing
         Note "Running $($asset.name). In its component list, tick 'GBA Development'."
         Start-Process -FilePath $exe -Wait
         Remove-Item $exe -ErrorAction SilentlyContinue
      }
   }

   Say "Make $DevkitProRoot visible to MSYS2 as /opt/devkitpro"
   $fstab = "$Msys2Root\etc\fstab"
   $mountLine = "$($DevkitProRoot.Replace('\','/')) /opt/devkitpro ntfs binary,noacl 0 0"
   if (-not $DryRun -and -not (Test-Path $fstab)) { Fail "MSYS2 fstab not found at $fstab" }
   if ((Test-Path $fstab) -and (Select-String -Path $fstab -SimpleMatch '/opt/devkitpro' -Quiet)) {
      Skip '/opt/devkitpro mount present'
   } else {
      Invoke-Step "back up $fstab and append: $mountLine" {
         Copy-Item $fstab "$fstab.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
         Add-Content -Path $fstab -Value $mountLine
      }
   }
}

# --- Verify -------------------------------------------------------------------------
if ($DryRun) { Say 'Dry run finished; nothing was changed'; exit 0 }

$failed = $false
function Test-Item([string]$Label, [scriptblock]$Test) {
   $ok = $false
   try { $ok = [bool](& $Test) } catch { $ok = $false }
   if ($ok) { Note "ok       $Label" } else { Note "MISSING  $Label"; $script:failed = $true }
}

if ($DoGba) {
   Say 'Verify GBA toolchain'
   Test-Item 'devkitARM' { Test-Path "$DevkitProRoot\devkitARM\bin\arm-none-eabi-g++.exe" }
   Test-Item 'libgba' { Test-Path "$DevkitProRoot\libgba\lib\libgba.a" }
   Test-Item 'gbafix' { Test-Path "$DevkitProRoot\tools\bin\gbafix.exe" }
   Test-Item 'C++20 for arm7tdmi (via /opt/devkitpro in MSYS2)' {
      (Invoke-Ucrt64 'd=$(mktemp -d) && printf "consteval int f(){return 1;}\nint main(){return f()-1;}\n" > $d/t.cpp && /opt/devkitpro/devkitARM/bin/arm-none-eabi-g++ -std=c++20 -mthumb -mcpu=arm7tdmi -c $d/t.cpp -o $d/t.o' -Quiet) -eq 0
   }
}
if ($DoDesktop) {
   Say 'Verify desktop toolchain (MSYS2 UCRT64)'
   Test-Item 'g++'     { (Invoke-Ucrt64 'command -v g++' -Quiet) -eq 0 }
   Test-Item 'make'    { (Invoke-Ucrt64 'command -v make' -Quiet) -eq 0 }
   Test-Item 'cmake'   { (Invoke-Ucrt64 'command -v cmake' -Quiet) -eq 0 }
   Test-Item 'python3' { (Invoke-Ucrt64 'command -v python3' -Quiet) -eq 0 }
   Test-Item 'SDL2'    { (Invoke-Ucrt64 'pkg-config --exists sdl2' -Quiet) -eq 0 }
   Test-Item 'git'     { [bool](Get-Command git -ErrorAction SilentlyContinue) }
   Test-Item 'mGBA'    { [bool](Get-Command mGBA -ErrorAction SilentlyContinue) -or (Test-Path "$env:ProgramFiles\mGBA\mGBA.exe") }
   Test-Item 'toolkit environment (.venv, editors)' {
      $py = Find-PyLauncher
      if (-not $py) { return $false }
      & $py -3.12 $EnvScript status --check | Out-Null
      return ($LASTEXITCODE -eq 0)
   }
}
if ($failed) { Fail 'some components are missing (see above). A new terminal may be needed for PATH changes.' }
Say 'Ready. Build from the "MSYS2 UCRT64" shell.'
