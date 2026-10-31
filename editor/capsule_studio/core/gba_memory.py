"""![S6] The GBA memory settings and the link's memory report (engine UM, D-33).

Two CMake cache settings of a build folder decide what the GBA link accepts (the engine's CMakeLists.txt and
cmake/gba_memory.ld): CAPSULE_GBA_MEMORY_CHECKS (ON: the link fails when EWRAM's 256 KB are passed or IWRAM leaves
less stack than the reserve; OFF only to measure a program that does not fit) and CAPSULE_GBA_STACK_RESERVE (bytes of
IWRAM kept free below the user stack). They are a build folder's, not a game's: they live in its CMakeCache.txt, which
cmake-gui edits too and the next build reads again. The screen arena's size is a game's build setting
(screen_arena_bytes in reference/project.json; core.project), which a cache value CAPSULE_SCREEN_ARENA_BYTES
overrides for every game of the folder.

After every GBA link the engine prints a line per program (cmake/gba_memory_report.cmake):
  GBA memory (NAME): EWRAM U of 262144 B (F B free); IWRAM code + data U of 32768 B, stack S B (reserve R B)
parse_log() reads those lines and the link's failure messages from a build's output; report_from_elf() makes the same
numbers from a linked program with nm (its __sbss_end__, __iheap_start and __sp_usr), so the studio shows the margins
of a build folder without building. Nothing here imports Qt.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import engine

## The build folder's cache file.
CACHE_FILE = "CMakeCache.txt"
## D-40 RG: a game's folder of build folders, one per preset (the umbrella's ./build PRESET --game FOLDER).
GAME_BUILDS = "build"
## The memory checks' cache option.
CHECKS = "CAPSULE_GBA_MEMORY_CHECKS"
## The stack reserve's cache setting.
RESERVE = "CAPSULE_GBA_STACK_RESERVE"
## The screen arena's cache override (empty: each game's build setting).
ARENA = "CAPSULE_SCREEN_ARENA_BYTES"
## The cache entry only a GBA build folder has (the header fixer the engine finds for GBA builds).
GBAFIX = "CAPSULE_GBAFIX"
## The cache's nm (CMAKE_NM).
NM = "CMAKE_NM"
## The cache entry types of the settings written here.
CACHE_TYPES = {CHECKS: "BOOL", RESERVE: "STRING", ARENA: "STRING"}
## The engine's default stack reserve when its CMakeLists.txt cannot be read.
DEFAULT_RESERVE = 2048
## The smallest and largest reserve offered (IWRAM is 32 KB).
MIN_RESERVE, MAX_RESERVE = 0, 32768
## A cache line: NAME:TYPE=VALUE.
CACHE_LINE = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_.-]*):(?P<type>[A-Z]+)=(?P<value>.*)$")
## CMake's true words.
TRUE_WORDS = {"1", "ON", "YES", "TRUE", "Y"}
## The report line (gba_memory_report.cmake).
REPORT_LINE = re.compile(r"GBA memory \((?P<name>[^)]*)\): EWRAM (?P<ewram_used>-?\d+) of (?P<ewram_bytes>\d+) B "
                         r"\((?P<ewram_free>-?\d+) B free\); IWRAM code \+ data (?P<iwram_used>-?\d+) of "
                         r"(?P<iwram_bytes>\d+) B, stack (?P<stack>-?\d+) B \(reserve (?P<reserve>\d+) B\)"
                         r"(?P<verdict>.*)$")
## The link's failures (gba_memory.ld's ASSERT messages).
LINK_FAILURE = re.compile(r"GBA memory: (?P<what>EWRAM|IWRAM) [^\"\n]*")
## The symbols the report reads.
SYMBOLS = ("__sbss_end__", "__iheap_start", "__sp_usr")
## An nm line: address, kind, name.
NM_LINE = re.compile(r"^(?P<addr>[0-9a-fA-F]+) [A-Za-z] (?P<name>\S+)$")
## Region starts and sizes when the engine's report script cannot be read (gba_cart.ld's ewram / iwram).
DEFAULT_REGIONS = {"ewram_start": 0x02000000, "ewram_bytes": 262144, "iwram_start": 0x03000000,
                   "iwram_bytes": 32768}
## The engine's report script (its region numbers are read from it).
REPORT_SCRIPT = ("cmake", "gba_memory_report.cmake")
## A "set(name value)" line of the report script.
SET_LINE = re.compile(r"set\((?P<name>\w+)\s+(?P<value>0x[0-9a-fA-F]+|\d+)\)")
## An ELF file's magic and the ELF header's e_machine offset; EM_ARM.
ELF_MAGIC, MACHINE_OFFSET, EM_ARM = b"\x7fELF", 18, 40
## Bytes of e_machine.
MACHINE_BYTES = 2
## Folder depth searched for linked programs.
ELF_DEPTH = 3
## Seconds nm may take.
NM_TIMEOUT = 30
## Percent.
PERCENT = 100
## nm prints addresses in hex.
HEX_BASE = 16


class GbaMemoryError(ValueError):
   """!A build folder or program that cannot be read."""


@dataclass
class Report:
   """!One program's memory use (a report line, or report_from_elf())."""

   ## The program.
   name: str
   ## EWRAM used (.ewram + .sbss), bytes.
   ewram_used: int
   ## EWRAM's size.
   ewram_bytes: int
   ## IWRAM code and data, bytes.
   iwram_used: int
   ## IWRAM's size.
   iwram_bytes: int
   ## Stack left below __sp_usr, bytes.
   stack: int
   ## The reserve it was checked against.
   reserve: int

   @property
   def ewram_free(self) -> int:
      """!EWRAM left (negative: over).
      @return bytes
      """
      return self.ewram_bytes - self.ewram_used

   @property
   def fits(self) -> bool:
      """!Whether the program fits (the link with the checks on would pass).
      @return True when EWRAM is not passed and the stack has its reserve
      """
      r = self   # through another name: Doxygen 1.12 takes members read here for undocumented ones
      return r.ewram_free >= 0 and r.stack >= r.reserve

   def problems(self) -> list[str]:
      """!What does not fit.
      @return messages
      """
      out = []
      r = self   # through another name (see fits)
      if r.ewram_free < 0:
         out.append(f"EWRAM is {-r.ewram_free} B over its {r.ewram_bytes} B: move screen state into the "
                    "screen arena (capsule/screen/arena.h)")
      if r.stack < r.reserve:
         out.append(f"IWRAM leaves {r.stack} B of stack, less than the {r.reserve} B reserve: move statics to "
                    "CAPSULE_EWRAM_BSS")
      return out

   def line(self) -> str:
      """!The report as the engine prints it.
      @return text
      """
      verdict = "" if self.fits else " - DOES NOT FIT"
      return (f"GBA memory ({self.name}): EWRAM {self.ewram_used} of {self.ewram_bytes} B ({self.ewram_free} B "
              f"free); IWRAM code + data {self.iwram_used} of {self.iwram_bytes} B, stack {self.stack} B (reserve "
              f"{self.reserve} B){verdict}")


# -- the cache -------------------------------------------------------------------------------------------------------


def cache_path(build: str | Path) -> Path:
   """!A build folder's cache file.
   @param build  the build folder
   @return its CMakeCache.txt
   @throws GbaMemoryError when it has none
   """
   p = Path(build) / CACHE_FILE
   if not p.is_file():
      raise GbaMemoryError(f"{build}: no {CACHE_FILE} (configure the build folder with CMake first)")
   return p


def read_cache(build: str | Path) -> dict[str, tuple[str, str]]:
   """!A build folder's cache entries.
   @param build  the build folder
   @return {name: (type, value)}
   """
   out = {}
   for line in cache_path(build).read_text(encoding="utf-8", errors="replace").splitlines():
      m = CACHE_LINE.match(line)
      if m:
         out[m.group("name")] = (m.group("type"), m.group("value"))
   return out


def is_gba(cache: dict[str, tuple[str, str]]) -> bool:
   """!Whether a cache configures a GBA build (devkitARM's toolchain, or the engine's GBA platform).
   @param cache  read_cache()'s
   @return True for a GBA build folder
   """
   toolchain = cache.get("CMAKE_TOOLCHAIN_FILE", ("", ""))[1].lower()
   return GBAFIX in cache or "gba" in Path(toolchain).name or "devkitarm" in toolchain


def engine_reserve() -> int:
   """!The engine's default stack reserve (its CMakeLists.txt).
   @return bytes
   """
   try:
      text = (engine.root() / "CMakeLists.txt").read_text(encoding="utf-8")
   except (OSError, engine.EngineNotFound):
      return DEFAULT_RESERVE
   m = re.search(r"set\(" + RESERVE + r"\s+(\d+)", text)
   return int(m.group(1)) if m else DEFAULT_RESERVE


@dataclass
class Settings:
   """!A build folder's GBA memory settings."""

   ## The memory checks are on.
   checks: bool
   ## The stack reserve, bytes.
   reserve: int
   ## The arena override, bytes, or None (each game's screen_arena_bytes).
   arena: int | None
   ## Whether the folder configures a GBA build.
   gba: bool


def settings(build: str | Path) -> Settings:
   """!A build folder's GBA memory settings (the engine's defaults for those it lacks).
   @param build  the build folder
   @return Settings
   """
   cache = read_cache(build)
   checks = cache.get(CHECKS, ("BOOL", "ON"))[1].upper() in TRUE_WORDS
   try:
      reserve = int(cache.get(RESERVE, ("STRING", str(engine_reserve())))[1], 0)
   except ValueError:
      reserve = engine_reserve()
   raw = cache.get(ARENA, ("STRING", ""))[1].strip()
   try:
      arena = int(raw, 0) if raw else None
   except ValueError:
      arena = None
   return Settings(checks, reserve, arena, is_gba(cache))


def set_cache(build: str | Path, name: str, value: str) -> None:
   """!Sets one cache entry (the line is replaced, or added with its type); CMake reads it at the next build.
   @param build  the build folder
   @param name   CHECKS, RESERVE or ARENA
   @param value  its value ("ON" / "OFF", a number, or "" for ARENA's default)
   @return None
   """
   if name not in CACHE_TYPES:
      raise GbaMemoryError(f"{name}: only {', '.join(CACHE_TYPES)} are set here")
   if name == CHECKS and value.upper() not in ("ON", "OFF"):
      raise GbaMemoryError(f"{CHECKS} is ON or OFF")
   if name == RESERVE:
      try:
         n = int(value, 0)
      except ValueError:
         raise GbaMemoryError(f"{RESERVE}: a number of bytes, got {value!r}") from None
      if not MIN_RESERVE <= n <= MAX_RESERVE:
         raise GbaMemoryError(f"{RESERVE}: {MIN_RESERVE}-{MAX_RESERVE} bytes")
   if name == ARENA and value:
      bs = engine.tool("build_settings")
      try:
         bs.BY_KEY["screen_arena_bytes"].parse(value)
      except (bs.SettingsError, KeyError) as e:
         raise GbaMemoryError(str(e)) from None
   path = cache_path(build)
   lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
   for i, line in enumerate(lines):
      m = CACHE_LINE.match(line)
      if m and m.group("name") == name:
         lines[i] = f"{name}:{m.group('type')}={value}"
         break
   else:
      lines.append(f"{name}:{CACHE_TYPES[name]}={value}")
   path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_folders(start: str | Path) -> list[Path]:
   """!Configured build folders in a folder, one level below it (a game's, the engine's) and in its build/ folder
   (D-40 RG: a game built with the umbrella's ./build PRESET --game FOLDER, in build/PRESET).
   @param start  the folder
   @return folders holding a CMakeCache.txt, GBA ones first
   """
   start = Path(start)
   found = [start] if (start / CACHE_FILE).is_file() else []
   for folder in (start, start / GAME_BUILDS):
      try:
         found += sorted(p for p in folder.iterdir() if p.is_dir() and (p / CACHE_FILE).is_file())
      except OSError:
         pass

   def gba_first(p: Path) -> tuple[bool, str]:
      """!Sort key: GBA folders first, then by name.
      @param p  a folder
      @return the key
      """
      try:
         return not is_gba(read_cache(p)), p.name
      except (GbaMemoryError, OSError):
         return True, p.name
   return sorted(found, key=gba_first)


# -- the report ------------------------------------------------------------------------------------------------------


def parse_log(text: str) -> tuple[list[Report], list[str]]:
   """!The memory report lines and the link failures in a build's output.
   @param text  the output
   @return (reports, failure messages)
   """
   reports, failures = [], []
   for line in text.splitlines():
      m = REPORT_LINE.search(line)
      if m:
         reports.append(Report(m.group("name"), int(m.group("ewram_used")), int(m.group("ewram_bytes")),
                               int(m.group("iwram_used")), int(m.group("iwram_bytes")), int(m.group("stack")),
                               int(m.group("reserve"))))
         continue
      f = LINK_FAILURE.search(line)
      if f and f.group(0) not in failures:
         failures.append(f.group(0).rstrip(".; "))
   return reports, failures


def regions() -> dict[str, int]:
   """!The memory regions the engine's report measures against (its cmake/gba_memory_report.cmake).
   @return {"ewram_start", "ewram_bytes", "iwram_start", "iwram_bytes"}
   """
   out = dict(DEFAULT_REGIONS)
   try:
      text = engine.root().joinpath(*REPORT_SCRIPT).read_text(encoding="utf-8")
   except (OSError, engine.EngineNotFound):
      return out
   for m in SET_LINE.finditer(text):
      if m.group("name") in out:
         out[m.group("name")] = int(m.group("value"), 0)
   return out


def report_from_symbols(nm_output: str, name: str, reserve: int) -> Report:
   """!A report from nm's listing of a linked program, as gba_memory_report.cmake computes it.
   @param nm_output  nm's output
   @param name       the program's name
   @param reserve    the stack reserve
   @return the Report
   """
   found = {}
   for line in nm_output.splitlines():
      m = NM_LINE.match(line.strip())
      if m and m.group("name") in SYMBOLS:
         found[m.group("name")] = int(m.group("addr"), HEX_BASE)
   missing = [s for s in SYMBOLS if s not in found]
   if missing:
      raise GbaMemoryError(f"{name} has no {', '.join(missing)} (not a GBA program linked by the engine)")
   r = regions()
   return Report(name, found["__sbss_end__"] - r["ewram_start"], r["ewram_bytes"],
                 found["__iheap_start"] - r["iwram_start"], r["iwram_bytes"],
                 found["__sp_usr"] - found["__iheap_start"], reserve)


def find_nm(build: str | Path | None = None) -> str | None:
   """!The nm to read programs with: the build folder's CMAKE_NM, else an ARM one on the path, else nm.
   @param build  a build folder, or None
   @return the program, or None
   """
   if build is not None:
      try:
         nm = read_cache(build).get(NM, ("", ""))[1]
      except GbaMemoryError:
         nm = ""
      if nm and Path(nm).is_file():
         return nm
   return shutil.which("arm-none-eabi-nm") or shutil.which("nm")


def report_from_elf(elf: str | Path, reserve: int, nm: str | None = None) -> Report:
   """!A linked program's memory use, read with nm.
   @param elf      the program
   @param reserve  the stack reserve to check against
   @param nm       nm to use (None: find_nm())
   @return the Report
   """
   exe = nm or find_nm()
   if exe is None:
      raise GbaMemoryError("no nm found (install devkitARM or binutils, or configure a GBA build folder)")
   try:
      out = subprocess.run([exe, str(elf)], capture_output=True, text=True, timeout=NM_TIMEOUT, check=False)
   except (OSError, subprocess.TimeoutExpired) as e:
      raise GbaMemoryError(f"{exe}: {e}") from None
   if out.returncode != 0:
      raise GbaMemoryError(f"{exe} {Path(elf).name}: {out.stderr.strip() or 'failed'}")
   return report_from_symbols(out.stdout, Path(elf).stem, reserve)


def is_arm_elf(path: Path) -> bool:
   """!Whether a file is an ARM ELF program.
   @param path  the file
   @return True for an ELF whose machine is ARM
   """
   try:
      with path.open("rb") as f:
         head = f.read(MACHINE_OFFSET + MACHINE_BYTES)
   except OSError:
      return False
   return head[:len(ELF_MAGIC)] == ELF_MAGIC and int.from_bytes(head[MACHINE_OFFSET:], "little") == EM_ARM


def programs(build: str | Path) -> list[Path]:
   """!The linked GBA programs of a build folder (*.elf, a few levels down).
   @param build  the build folder
   @return paths, newest first
   """
   base = Path(build)
   found = []
   for depth in range(ELF_DEPTH + 1):
      found += [p for p in base.glob("/".join(["*"] * depth + ["*.elf"])) if p.is_file() and is_arm_elf(p)]
   return sorted(set(found), key=lambda p: -p.stat().st_mtime)


def folder_reports(build: str | Path) -> tuple[list[Report], list[str]]:
   """!The memory use of each GBA program of a build folder, with its own reserve.
   @param build  the build folder
   @return (reports, messages for programs that could not be read)
   """
   s = settings(build)
   nm = find_nm(build)
   reports, errors = [], []
   for elf in programs(build):
      try:
         reports.append(report_from_elf(elf, s.reserve, nm))
      except GbaMemoryError as e:
         errors.append(str(e))
   return reports, errors


def arena_share(report: Report, arena: int) -> str:
   """!How much of the EWRAM a program uses is the screen arena.
   @param report  the program's report
   @param arena   the arena's bytes
   @return a sentence
   """
   if arena > report.ewram_used:
      return (f"the screen arena ({arena} B) is more than the {report.ewram_used} B of EWRAM it uses: this program "
              "links no arena (it opens no screens) or a smaller one")
   share = arena * PERCENT // report.ewram_used
   return f"the screen arena ({arena} B) is {share}% of the {report.ewram_used} B of EWRAM it uses"
