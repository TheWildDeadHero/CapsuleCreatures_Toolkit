"""!Access to the engine's own build tools (asset compiler, bitmap, font, text encoder).

The editor never re-implements what the engine's compilers decide (palettes,
tile counts, code page, key hashing): it imports those modules from the
engine checkout so a preview matches the build.

The engine is found, in order, at (D-37 layout; relative to this repository):
  1. the directory in the CAPSULE_ENGINE environment variable;
  2. ../engine, the engine submodule beside this toolkit inside the
     CapsuleCreatures umbrella (CapsuleCreatures/toolkit and
     CapsuleCreatures/engine); in a prebuilt Studio download this is the
     engine copy the bundle ships beside the studio's sources;
  3. ../CapsuleCreatures_Engine: a standalone engine clone beside a
     standalone toolkit clone.
"""
from __future__ import annotations

import importlib
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

## Folders between this file and the repository root (core, capsule_studio, editor).
STUDIO_ROOT_DEPTH = 3
## Root of the capsule-studio repository (editor/capsule_studio/core -> repo).
STUDIO_ROOT = Path(__file__).resolve().parents[STUDIO_ROOT_DEPTH]
## The engine submodule's folder inside the umbrella, beside this toolkit (toolkit/ and engine/).
ENGINE_SUBMODULE = "engine"
## Standalone engine clones beside a standalone toolkit clone (the public repository's folder name).
ENGINE_CLONES = ("CapsuleCreatures_Engine",)
## Environment variable naming an engine checkout.
ENV_VAR = "CAPSULE_ENGINE"
## OBJ tiles per sprite slot when the engine header cannot be read (gfx::sprites::kTilesPerSlot).
DEFAULT_TILES_PER_SLOT = 64


class EngineNotFound(Exception):
   """!No engine checkout with tools/asset_compiler.py could be found."""
   pass


def candidates() -> list[Path]:
   """!Directories that may hold the engine, in search order.
   @return list of Paths
   """
   out = []
   if os.environ.get(ENV_VAR):
      out.append(Path(os.environ[ENV_VAR]).expanduser())
   out.append(STUDIO_ROOT.parent / ENGINE_SUBMODULE)
   out += [STUDIO_ROOT.parent / clone for clone in ENGINE_CLONES]
   return out


## Cached engine root once found.
_root: Path | None = None


def root() -> Path:
   """!The engine checkout in use.
   @return Path of the engine root
   @throws EngineNotFound when none of candidates() has the tools
   """
   global _root
   if _root is None:
      for c in candidates():
         if (c / "tools" / "asset_compiler.py").is_file():
            _root = c.resolve()
            break
      else:
         raise EngineNotFound("capsule-engine not found; set " + ENV_VAR + " to its directory "
                              "(searched: " + ", ".join(str(c) for c in candidates()) + ")")
      # The engine's tool modules import each other by bare name, so tools/ goes on the path.
      tools = str(_root / "tools")
      if tools not in sys.path:
         sys.path.insert(0, tools)
   return _root


def tool(name: str) -> ModuleType:
   """!Imports one of the engine's tool modules.
   @param name  module name in the engine's tools/ (e.g. "bitmap")
   @return the module
   """
   root()
   return importlib.import_module(name)


def bitmap() -> ModuleType:
   """!The engine's bitmap module (PNG, palettes).
   @return module
   """
   return tool("bitmap")


def asset_compiler() -> ModuleType:
   """!The engine's asset compiler module.
   @return module
   """
   return tool("asset_compiler")


def font_glyphs(codepage: Any = None, fonts: Sequence[Path] | None = None) -> dict[int, list[list[int]]]:
   """!A font as 8x8 cells by code, the way the build lays it out for a code
   page (font_compiler.py): each code the page maps shows the glyph of its
   character. Codes whose character has no glyph are left out (the build
   refuses them; core.codepage.font_problems() says which).
   @param codepage  text_encoder.CodePage, or None for the engine's default (ASCII) page
   @param fonts     font files (the first is the font, the others add glyphs), or None for the engine's
                    default font
   @return dict code -> 8 rows of 8 pixel values (0 empty, 1 ink, 2 shadow)
   """
   fc = tool("font_compiler")
   page = codepage if codepage is not None else tool("text_encoder").DEFAULT
   files = list(fonts) if fonts else [root() / "assets" / "fonts" / "default_8x8.txt"]
   chars: dict[str, list[str]] = {}
   for f in files:
      # A character defined twice keeps its first glyph here; the build reports it.
      for ch, rows in fc.parse_characters(Path(f)).items():
         chars.setdefault(ch, rows)
   return {code: fc.render(chars[ch]) for code, ch in page.chars.items() if ch in chars}


_INT_LITERAL = r"(0[xX][0-9a-fA-F']+|0[bB][01']+|\d[\d']*)[uUlL]*\b"
"""!A C++ integer literal after "=" (group 1: its digits with the prefix, without the suffix)."""

_HEX_BASE = 16
_BINARY_BASE = 2
_OCTAL_BASE = 8
_DECIMAL_BASE = 10
_RADIX_PREFIX = len("0x")   # "0x" / "0b" before the digits


def cpp_int(literal: str) -> int:
   """!The value of a C++ integer literal without its suffix ("0x40", "0b101", "010", "1'000", "64").
   @param literal  the literal's prefix and digits
   @return its value
   """
   digits = literal.replace("'", "")
   lower = digits.lower()
   if lower.startswith("0x"):
      return int(digits[_RADIX_PREFIX:], _HEX_BASE)
   if lower.startswith("0b"):
      return int(digits[_RADIX_PREFIX:], _BINARY_BASE)
   if len(digits) > 1 and digits.startswith("0"):
      # a leading 0 makes the literal octal in C++
      return int(digits[1:], _OCTAL_BASE)
   return int(digits, _DECIMAL_BASE)


def header_constant(header: str, name: str, default: int) -> int:
   """!Reads an integer constant from an engine header, so editor limits
   follow the engine's VRAM plan.
   @param header   path below include/ (e.g. "capsule/gfx/sprites.h")
   @param name     constant name
   @param default  value when the header or constant is missing
   @return the value
   """
   try:
      text = (root() / "include" / header).read_text(encoding="utf-8")
   except (OSError, EngineNotFound):
      return default
   # The first "name = literal" in the header, e.g. "inline constexpr int kTilesPerSlot = 64;" or
   # "... kBlendMax = 0x10u;": a C++ integer literal (hex, binary, octal or decimal, digit separators, suffixes).
   m = re.search(r"\b" + re.escape(name) + r"\s*=\s*" + _INT_LITERAL, text)
   if m is None:
      return default
   try:
      return cpp_int(m.group(1))
   except ValueError:
      # not a literal this reader knows (e.g. "09", a bad octal one): the default, as for a missing constant
      return default


def sprite_tiles_per_slot() -> int:
   """!OBJ tiles a sprite asset may use across all frames (gfx::sprites::kTilesPerSlot).
   @return tile count
   """
   return header_constant("capsule/gfx/sprites.h", "kTilesPerSlot", DEFAULT_TILES_PER_SLOT)
