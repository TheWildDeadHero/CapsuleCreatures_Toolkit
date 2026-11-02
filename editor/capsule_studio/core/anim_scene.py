"""![S8] The engine sandbox's scene viewer for the Studio (M5, D-38; the engine's apps/sandbox_anim).

The engine's scene kit sandbox runs its scenes (scenes.h: affine animation, scanline effects, palette blends and the
animation-script player, kSceneFrames frames each, in turn) frame by frame with no input. Its viewer,
`capsule_anim_view` (built with the engine's tests, cmake/parts/anim.cmake), plays them on the engine's software
video model and writes chosen frames as raw little-endian BGR555, 240 x 160 each:

   capsule_anim_view --frames 1,60,... --out FILE      frame k: the picture after the k-th vertical blank
   capsule_anim_view --check                            two rounds; checks the report and prints a frame hash

This module finds the viewer, runs it for the frames the panel shows (at most VIEWER_MAX_FRAMES a run; frames are
kept once read), turns BGR555 into RGB and reads the scenes' names and lengths from the sandbox's scenes.h, so the
Studio shows the engine's own pictures, never its own idea of them. Nothing here needs Qt.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from . import engine

## Environment variable naming the viewer program.
VIEWER_ENV = "CAPSULE_ANIM_VIEW"
## The viewer's program name (".exe" is tried too).
VIEWER_NAME = "capsule_anim_view"
## Suffix of a Windows program.
EXE_SUFFIX = ".exe"
## Engine folders searched for a build (their names start with this), and how deep the program may sit in one.
BUILD_PREFIX = "build"
## How deep the viewer may sit in a build folder.
BUILD_DEPTH = 3
## The sandbox's scenes header, below the engine root.
SCENES_HEADER = Path("apps") / "sandbox_anim" / "src" / "scenes.h"
## Fallback scene settings (scenes.h kScenes, kSceneFrames) when the header cannot be read.
FALLBACK_SCENES = 4
## Fallback of scenes.h kSceneFrames.
FALLBACK_SCENE_FRAMES = 180
## Frames the viewer writes in one run (anim_view.cpp kMaxFrames).
VIEWER_MAX_FRAMES = 256
## Frames frame() asks for in one run when a frame is missing (the frame and those after it, for playback).
READ_AHEAD = 60
## Seconds a viewer run may take.
VIEWER_TIMEOUT = 60
## Frame size, pixels (the software video model's).
FRAME_WIDTH = 240
## Frame height, pixels.
FRAME_HEIGHT = 160
## Bytes of a BGR555 pixel.
PIXEL_BYTES = 2
## Bytes of an RGB pixel.
RGB_BYTES = 3
## Bits of a 5-bit channel, its mask, and the shifts of green and blue in BGR555.
CHANNEL_BITS = 5
## A 5-bit channel's mask.
CHANNEL_MASK = 0x1F
## Green's shift in BGR555.
GREEN_SHIFT = 5
## Blue's shift in BGR555.
BLUE_SHIFT = 10
## A 5-bit channel to 8 bits: c << 3 | c >> 2.
WIDEN_SHIFT = 3
## A 5-bit channel's top bits repeated below: c >> this.
WIDEN_BACK = 2
## Bits of a byte.
BYTE_BITS = 8


class ViewerError(RuntimeError):
   """!The viewer is missing or a run failed."""


@dataclass(frozen=True)
class Scene:
   """!One of the sandbox's scenes."""

   ## Its number.
   index: int
   ## Its name (scenes.h's doc: "0 affine (...)").
   name: str
   ## Its first frame (1-based, as the viewer counts).
   first: int
   ## Its frames.
   frames: int


def _header() -> str:
   """!The sandbox's scenes.h, or "" without an engine checkout.
   @return its text
   """
   try:
      return (engine.root() / SCENES_HEADER).read_text(encoding="utf-8")
   except (OSError, engine.EngineNotFound):
      return ""


def scenes() -> list[Scene]:
   """!The sandbox's scenes, in turn (names and lengths from scenes.h).
   @return Scene list
   """
   text = _header()
   count = _int(text, "kScenes", FALLBACK_SCENES)
   frames = _int(text, "kSceneFrames", FALLBACK_SCENE_FRAMES)
   # the header's doc names them: "Scenes, ... in turn: 0 affine (...), 1 scanline (...", one word each
   names = dict((int(n), w) for n, w in re.findall(r"\b(\d+) ([a-z]+) \(", text))
   return [Scene(i, names.get(i, f"scene {i}"), i * frames + 1, frames) for i in range(count)]


def _int(text: str, name: str, fallback: int) -> int:
   """!A decimal constant of a header's text.
   @param text      the header
   @param name      its name
   @param fallback  value when it is missing
   @return the value
   """
   m = re.search(r"\b" + re.escape(name) + r"\s*=\s*(\d+)\s*;", text)
   return int(m.group(1)) if m else fallback


def total_frames() -> int:
   """!Frames of one round of every scene.
   @return frames
   """
   return sum(s.frames for s in scenes())


def scene_of(frame: int) -> Scene | None:
   """!The scene a frame of a round shows.
   @param frame  1-based frame
   @return Scene, or None outside the round
   """
   return next((s for s in scenes() if s.first <= frame < s.first + s.frames), None)


def viewer_candidates() -> list[Path]:
   """!Where the viewer may be: VIEWER_ENV, then the engine checkout's build folders.
   @return paths, in search order
   """
   out = []
   if os.environ.get(VIEWER_ENV):
      out.append(Path(os.environ[VIEWER_ENV]).expanduser())
   try:
      root = engine.root()
   except engine.EngineNotFound:
      return out
   for build in sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith(BUILD_PREFIX)):
      for depth in range(BUILD_DEPTH):
         pattern = "/".join(["*"] * depth + [VIEWER_NAME + "*"])
         out += sorted(p for p in build.glob(pattern) if p.stem == VIEWER_NAME)
   return out


def find_viewer() -> Path | None:
   """!The first viewer program found (viewer_candidates()).
   @return its path, or None
   """
   for p in viewer_candidates():
      if p.is_file() and os.access(p, os.X_OK):
         return p
   return None


def bgr555_to_rgb(raw: bytes) -> bytes:
   """!Little-endian BGR555 pixels as 8-bit RGB (each 5-bit channel widened: c << 3 | c >> 2).
   @param raw  2 bytes a pixel
   @return 3 bytes a pixel
   """
   widen = [(c << WIDEN_SHIFT) | (c >> WIDEN_BACK) for c in range(CHANNEL_MASK + 1)]
   out = bytearray(len(raw) // PIXEL_BYTES * RGB_BYTES)
   at = 0
   for i in range(0, len(raw) - 1, PIXEL_BYTES):
      v = raw[i] | (raw[i + 1] << BYTE_BITS)
      out[at] = widen[v & CHANNEL_MASK]
      out[at + 1] = widen[(v >> GREEN_SHIFT) & CHANNEL_MASK]
      out[at + RGB_BYTES - 1] = widen[(v >> BLUE_SHIFT) & CHANNEL_MASK]
      at += RGB_BYTES
   return bytes(out)


class Viewer:
   """!Runs the viewer and keeps the frames it wrote."""

   def __init__(self, program: str | Path) -> None:
      """!A viewer.
      @param program  the capsule_anim_view program
      @throws ViewerError when it is not a program
      """
      ## The viewer's path.
      self.program = Path(program)
      if not self.program.is_file():
         raise ViewerError(f"{self.program.name}: no such program")
      ## Raw BGR555 pixels by 1-based frame (FRAME_WIDTH x FRAME_HEIGHT each), for the frames read so far.
      self.frames: dict[int, bytes] = {}
      ## RGB pixels by 1-based frame, for the frames shown so far.
      self.rgb: dict[int, bytes] = {}

   def frame(self, number: int) -> bytes:
      """!One frame's picture (read with the READ_AHEAD frames after it in one run when it is missing).
      @param number  1-based frame
      @return RGB pixels
      @throws ViewerError when the run fails
      """
      if number not in self.rgb:
         if number not in self.frames:
            self.read(range(number, number + READ_AHEAD))
         self.rgb[number] = bgr555_to_rgb(self.frames[number])
      return self.rgb[number]

   def read(self, numbers: Iterable[int]) -> None:
      """!Reads frames (those not read yet), VIEWER_MAX_FRAMES a run.
      @param numbers  1-based frames
      @return None
      @throws ViewerError when a run fails
      """
      wanted = sorted({n for n in numbers if n >= 1 and n not in self.frames})
      for start in range(0, len(wanted), VIEWER_MAX_FRAMES):
         chunk = wanted[start:start + VIEWER_MAX_FRAMES]
         raw = self._run(chunk)
         size = FRAME_WIDTH * FRAME_HEIGHT * PIXEL_BYTES
         if len(raw) != size * len(chunk):
            raise ViewerError(f"the viewer wrote {len(raw)} bytes for {len(chunk)} frames ({size} each)")
         for i, n in enumerate(chunk):
            self.frames[n] = raw[i * size:(i + 1) * size]

   def _run(self, chunk: list[int]) -> bytes:
      """!One viewer run writing a list of frames.
      @param chunk  1-based frames, ascending
      @return the raw BGR555 bytes
      @throws ViewerError when it fails
      """
      with tempfile.TemporaryDirectory(prefix="capsule_anim_view_") as folder:
         out = Path(folder) / "frames.raw"
         args = [str(self.program), "--frames", ",".join(str(n) for n in chunk), "--out", str(out)]
         try:
            done = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                  errors="replace", timeout=VIEWER_TIMEOUT)
         except (OSError, subprocess.TimeoutExpired) as e:
            raise ViewerError(f"{self.program.name}: {e}") from e
         if done.returncode != 0 or not out.is_file():
            raise ViewerError(f"{self.program.name} failed ({done.returncode}): {done.stdout.strip()}")
         return out.read_bytes()

   def check(self) -> tuple[bool, str]:
      """!The viewer's --check (two rounds of every scene, the report checked).
      @return (passed, its output)
      @throws ViewerError when it cannot run
      """
      try:
         done = subprocess.run([str(self.program), "--check"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, errors="replace", timeout=VIEWER_TIMEOUT)
      except (OSError, subprocess.TimeoutExpired) as e:
         raise ViewerError(f"{self.program.name}: {e}") from e
      return done.returncode == 0, done.stdout.strip()
