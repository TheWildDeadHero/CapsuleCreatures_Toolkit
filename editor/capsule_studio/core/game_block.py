"""!A test save's Game section [S5] (engine N3: capsule::save::Section::Game, id 5; save::GameBlock): a game's own
block of the save image (its bytes as they are, with the game's version of their layout), next to the engine's
bag, party, boxes, script banks and nursery.

The block's size and version are the game's C++ (capsule::save::game_block_bytes() and the version it passes in
its GameBlock), so a test save states them: {"game": {"version": V, "size": N, "bytes": "hex"}} (bytes past the
hex are zeros). The engine loads the section only when its version and size are the destination's (else it is
another shape and left out), so set() takes them from the game, or from_image() reads them from a save the game
wrote (an engine save image: the newest valid copy's Game section). image() writes the test save's image with the
section: the engine's tools/save_layout.py image() for the other sections, its game_payload() for this one and its
assemble() for the whole (save_layout's own image() has no Game argument). available() says whether the engine's
save layout has the section (an engine before N3 has none).

Qt-free; the Test save page's Game box (ui/editors/content/test_save.py) and `testsave game` use it.
"""
from __future__ import annotations

import binascii
import struct
from pathlib import Path
from typing import Any

from . import engine
from .document import Document, DocumentError

## A parsed JSON object.
JsonDict = dict[str, Any]
## The test save's key of the Game section.
GAME_KEY = "game"
## The section's name in the engine's save layout (save_layout.SECTIONS).
SECTION = "game"
## The block's settings in a test save.
VERSION_KEY, SIZE_KEY, BYTES_KEY = "version", "size", "bytes"
## Highest layout version (GameBlock::version is a u16).
MAX_VERSION = 0xFFFF
## Bytes the editor shows per hex row.
ROW_BYTES = 16
## Little-endian layouts of the image header's fields after the magic (save_layout.assemble(): magic u32, version u16,
## section count u8, a reserved byte, sequence u32, payload bytes u32, checksum u32) and of a section entry (id u8,
## version u8, two reserved bytes, bytes u32, checksum u32).
HEADER_LAYOUT, ENTRY_LAYOUT = "<IHBBIII", "<BBHII"
## Byte alignment the image copies start at when one is searched for (the medium's slots are larger multiples).
COPY_ALIGN = 4


def tool() -> Any:
   """!The engine's tools/save_layout.py.
   @return the module
   """
   return engine.tool("save_layout")


def available() -> bool:
   """!Whether the engine's save layout has a Game section (engine N3).
   @return True when it does
   """
   try:
      return SECTION in tuple(getattr(tool(), "SECTIONS", ()))
   except engine.EngineNotFound:
      return False


def game_of(save: Document) -> JsonDict | None:
   """!A test save's Game section settings.
   @param save  test save Document
   @return {"version", "size", "bytes"} (a copy), or None without one
   """
   found = save.data.get(GAME_KEY)
   return dict(found) if isinstance(found, dict) else None


def block_of(save: Document) -> bytes | None:
   """!The block's bytes as the image holds them (the hex, zeros up to the size).
   @param save  test save Document
   @return bytes, or None without a section
   @throws DocumentError for bytes that are no hex or longer than the size
   """
   g = game_of(save)
   if g is None:
      return None
   size = int(g.get(SIZE_KEY, 0))
   data = _unhex(str(g.get(BYTES_KEY, "")))
   if len(data) > size:
      raise DocumentError(f"the game block holds {len(data)} bytes; its size is {size}")
   return data + bytes(size - len(data))


def _unhex(text: str) -> bytes:
   """!Bytes from hex (spaces and line breaks allowed).
   @param text  hex digits
   @return bytes
   @throws DocumentError for something else
   """
   try:
      return binascii.unhexlify("".join(text.split()))
   except (binascii.Error, ValueError):
      raise DocumentError("the game block's bytes are hex digits (two per byte)") from None


def set_game(save: Document, version: int, size: int, data: bytes = b"") -> None:
   """!Gives a test save a Game section (call inside save.edit()): the game's layout version, its block's size and the
   block's first bytes (the rest zeros; trailing zeros are not written).
   @param save     test save Document
   @param version  the game's version of its block (0-65535)
   @param size     its bytes (game_block_bytes(); 1 or more)
   @param data     the bytes (at most size)
   @return None
   @throws DocumentError for a version, size or data the engine would not load
   """
   if not available():
      raise DocumentError("the engine's save layout has no Game section (it came with engine N3)")
   if isinstance(version, bool) or not isinstance(version, int) or not 0 <= version <= MAX_VERSION:
      raise DocumentError(f"a game block's version is 0-{MAX_VERSION}")
   if isinstance(size, bool) or not isinstance(size, int) or size < 1:
      raise DocumentError("a game block has 1 byte or more (the game's game_block_bytes())")
   if len(data) > size:
      raise DocumentError(f"{len(data)} bytes do not fit a {size}-byte block")
   save.data[GAME_KEY] = {VERSION_KEY: version, SIZE_KEY: size, BYTES_KEY: data.rstrip(b"\0").hex()}


def set_bytes(save: Document, offset: int, data: bytes) -> None:
   """!Writes bytes into the block at an offset (call inside save.edit()).
   @param save    test save Document (with a Game section)
   @param offset  the first byte
   @param data    the bytes
   @return None
   @throws DocumentError past the block's end
   """
   g = game_of(save)
   block = block_of(save)
   if g is None or block is None:
      raise DocumentError("the test save has no game block (set one first)")
   if offset < 0 or offset + len(data) > len(block):
      raise DocumentError(f"bytes {offset}-{offset + len(data) - 1} are past the {len(block)}-byte block")
   set_game(save, int(g[VERSION_KEY]), len(block), block[:offset] + data + block[offset + len(data):])


def clear_game(save: Document) -> None:
   """!Takes the Game section out of a test save (call inside save.edit()).
   @param save  test save Document
   @return None
   """
   save.data.pop(GAME_KEY, None)


def check_game(save: Document) -> list[str]:
   """!What the engine would refuse in a test save's Game section.
   @param save  test save Document
   @return problems ([] when it exports)
   """
   g = game_of(save)
   if g is None:
      return []
   out = []
   if not available():
      out.append("game: the engine's save layout has no Game section (engine N3)")
   version, size = g.get(VERSION_KEY), g.get(SIZE_KEY)
   if isinstance(version, bool) or not isinstance(version, int) or not 0 <= version <= MAX_VERSION:
      out.append(f"game: version {version!r} (0-{MAX_VERSION})")
   if isinstance(size, bool) or not isinstance(size, int) or size < 1:
      out.append(f"game: size {size!r} (1 or more bytes)")
   else:
      try:
         block_of(save)
      except DocumentError as e:
         out.append(f"game: {e}")
   return out


def payload(save: Document) -> bytes:
   """!The Game section's bytes (save_layout.game_payload()).
   @param save  test save Document
   @return the payload (empty without a section)
   """
   block = block_of(save)
   g = game_of(save)
   if block is None or g is None:
      return b""
   return bytes(tool().game_payload(block, int(g[VERSION_KEY])))


def sections(image: bytes) -> tuple[int, dict[str, bytes]] | None:
   """!One copy of an engine save image read back: its sequence and its sections' payloads (the header's magic and
   checksum, each section's checksum checked as save_layout.assemble() writes them).
   @param image  bytes starting at a copy's header
   @return (sequence, {section name: payload}), or None when no valid copy starts there
   """
   sl = tool()
   if len(image) < sl.HEADER_BYTES:
      return None
   magic, _version, count, _reserved, sequence, size, checksum = struct.unpack_from(HEADER_LAYOUT, image)
   if magic != sl.MAGIC or len(image) < sl.HEADER_BYTES + size:
      return None
   head = image[:sl.CHECKSUM_OFFSET]
   tail = image[sl.CHECKSUM_OFFSET + sl.CHECKSUM_BYTES:sl.HEADER_BYTES]
   table = image[sl.HEADER_BYTES:sl.HEADER_BYTES + count * sl.SECTION_ENTRY_BYTES]
   if sl.fnv(table, sl.fnv(tail, sl.fnv(head))) != checksum:
      return None
   out = {}
   at = sl.HEADER_BYTES + len(table)
   for i in range(count):
      sid, _ver, _res, n, fnv = struct.unpack_from(ENTRY_LAYOUT, table, i * sl.SECTION_ENTRY_BYTES)
      body = image[at:at + n]
      at += n
      if sid >= len(sl.SECTIONS) or len(body) != n or sl.fnv(body) != fnv:
         return None
      out[sl.SECTIONS[sid]] = body
   return sequence, out


def newest_copy(data: bytes) -> tuple[int, dict[str, bytes]] | None:
   """!The newest valid copy in a save file (copies are searched at every COPY_ALIGN bytes: a medium's slots).
   @param data  the file's bytes
   @return (sequence, sections), or None without a valid copy
   """
   magic = struct.pack("<I", tool().MAGIC)
   best = None
   at = data.find(magic)
   while at >= 0:
      if at % COPY_ALIGN == 0:
         found = sections(data[at:])
         if found is not None and (best is None or found[0] > best[0]):
            best = found
      at = data.find(magic, at + 1)
   return best


def from_image(save: Document, path: str | Path) -> int:
   """!Takes the Game section of a save file the game wrote (its newest valid copy; call inside save.edit()).
   @param save  test save Document
   @param path  the save file
   @return the block's size
   @throws DocumentError when the file holds no valid copy or no Game section
   """
   try:
      data = Path(path).read_bytes()
   except OSError as e:
      raise DocumentError(f"cannot read {path}: {e}") from None
   found = newest_copy(data)
   if found is None:
      raise DocumentError(f"{Path(path).name} holds no engine save image")
   body = found[1].get(SECTION)
   head = tool().GAME_HEAD_BYTES
   if body is None or len(body) < head:
      raise DocumentError(f"{Path(path).name}'s newest copy has no Game section")
   version, size = struct.unpack_from("<HI", body)
   set_game(save, version, size, body[head:head + size])
   return size


def with_game(image: bytes, save: Document) -> bytes:
   """!An image with the test save's Game section added (the image's sections read back, the Game payload added, the
   whole assembled again by the engine's save_layout.assemble()).
   @param image  one copy (save_layout.image())
   @param save   test save Document
   @return the bytes (image itself without a Game section)
   """
   extra = payload(save)
   if not extra:
      return image
   found = sections(image)
   if found is None:
      raise DocumentError("the engine's save image could not be read back")
   sequence, parts = found
   parts[SECTION] = extra
   return bytes(tool().assemble(parts, sequence))


def hex_rows(save: Document) -> list[tuple[int, str]]:
   """!The block as hex rows.
   @param save  test save Document
   @return (offset, "xx xx ...") per ROW_BYTES bytes
   """
   block = block_of(save) or b""
   return [(i, block[i:i + ROW_BYTES].hex(" ")) for i in range(0, len(block), ROW_BYTES)]


def lines(save: Document) -> list[str]:
   """!The Game section as text (CLI `testsave show`).
   @param save  test save Document
   @return lines ([] without one)
   """
   g = game_of(save)
   if g is None:
      return []
   try:
      block = block_of(save) or b""
   except DocumentError as e:
      return [f"game block: {e}"]
   used = len(block.rstrip(b"\0"))
   return [f"game block: version {g.get(VERSION_KEY)}, {len(block)} bytes ({used} up to the last non-zero byte)"]
