"""![S8] Affine sprite animations for the Studio (M5, D-38; the engine's include/capsule/screen/affine.h).

An affine animation is a list of commands that scale and rotate a sprite through its matrix, frame by frame. The
engine keeps them as C++ data (`af::Cmd`, 6 bytes: two s16 and two u8, the reference layout); the Studio edits them
in an animation file and writes that C++ (export_cpp()):

   {"schema": "capsule.affine-anims/1",
    "anims": [{"name": "spin", "cmds": [{"op": "frame", "x_scale": 0, "y_scale": 0, "rotation": 4, "duration": 1},
                                        {"op": "jump", "target": 0}]}]}

Commands: "frame" (x_scale, y_scale: 8.8 changes; rotation: 1/256 turns, -128 to 127; duration: frames, 0 sets the
values at once), "loop" (count; 0 marks the loop's start), "jump" (target: a command index), "end".

simulate() steps an animation exactly as the engine's affine step does (src/screen/affine.cpp: begin_anim(),
continue_anim(), the loop's walk back to its marker, 8-bit command indices, 16-bit wrapping, the matrix rule with the
engine's integer sine read from include/capsule/core/trig.h), so the preview shows the numbers the engine computes.
Step 1 is the sprite's first affine step (the one sprites::create_and_animate() runs at once), each later step one
frame. Data the engine would read past (a jump or loop that leaves the list) and loops that never reach a frame are
reported instead of followed. Nothing here needs Qt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import engine

## Schema of an affine animation file.
SCHEMA = "capsule.affine-anims/1"
## Suffix the Studio gives an affine animation file.
FILE_SUFFIX = ".affine.json"

## The engine header with the command layout's constants.
AFFINE_HEADER = "capsule/screen/affine.h"
## The engine header with the quarter-wave sine table.
TRIG_HEADER = "capsule/core/trig.h"

## Command kinds, as the file names them.
OP_FRAME = "frame"
## A loop command's kind.
OP_LOOP = "loop"
## A jump command's kind.
OP_JUMP = "jump"
## The end command's kind.
OP_END = "end"
## Every kind, in the order the editor offers them.
OPS = (OP_FRAME, OP_LOOP, OP_JUMP, OP_END)

## Fallbacks for the header's constants (affine.h kTypeLoop / kTypeJump / kTypeEnd / kScaleOne): used only when no
## engine checkout is found; the values are the engine's.
FALLBACK_TYPE_LOOP = 0x7FFD
## Fallback of affine.h kTypeJump.
FALLBACK_TYPE_JUMP = 0x7FFE
## Fallback of affine.h kTypeEnd.
FALLBACK_TYPE_END = 0x7FFF
## Fallback of affine.h kScaleOne (scale 1.0, 8.8).
FALLBACK_SCALE_ONE = 0x100
## Fallback Q14 shift (trig.h kQ14Shift).
FALLBACK_Q14_SHIFT = 14

## A rotation byte's shift into the 16-bit turn (affine.h kRotationShift).
ROTATION_SHIFT = 8
## The rotation's low byte, cleared each step.
ROTATION_LOW_MASK = 0xFF
## 0x10000: a scale's inverse is this / scale.
ONE_SQUARED = 0x10000
## Bits of a 16-bit value.
BITS_16 = 16
## Values of a 16-bit word.
WORD_VALUES = 1 << BITS_16
## Smallest and largest s16.
S16_MIN = -0x8000
## Largest s16.
S16_MAX = 0x7FFF
## Values of a byte.
BYTE_VALUES = 0x100
## Smallest and largest s8 (a frame's rotation change).
S8_MIN = -0x80
## Largest s8.
S8_MAX = 0x7F
## Largest u8 (a duration; a command index).
U8_MAX = 0xFF
## A quarter-wave table step count (trig.h kQuarterSteps) and the quadrant layout.
QUARTER_STEPS = 64
## Step bits below the quadrant (trig.h kQuadrantShift).
QUADRANT_SHIFT = 6
## Step bits inside a quadrant (trig.h kQuarterStepMask).
QUARTER_STEP_MASK = 63
## First quadrant with a negative sine (trig.h kNegativeQuadrant).
NEGATIVE_QUADRANT = 2
## A quarter turn as a 16-bit turn.
QUARTER_TURN = 0x4000
## Steps simulate() runs when none is given.
DEFAULT_STEPS = 120
## Same-frame commands one step may follow before it is reported as a loop that never reaches a frame.
MAX_CHAIN = 256

## The sample's animations (the engine sandbox's scenes.cpp kSpin / kPulse / kSquash): the spin's turn per frame
## (1/256 turns), the pulse's scale step (8.8), frames and repeats, the squash's scale step and frames.
SAMPLE_SPIN_STEP = 4
## The sample pulse's scale step a frame (8.8).
SAMPLE_PULSE_STEP = 16
## Frames of each pulse half.
SAMPLE_PULSE_FRAMES = 8
## Repeats of the pulse loop.
SAMPLE_PULSE_REPEATS = 3
## The sample squash's scale step a frame (8.8).
SAMPLE_SQUASH_STEP = 8
## Frames of each squash half.
SAMPLE_SQUASH_FRAMES = 12

## Name of the C++ namespace alias export_cpp() writes (the sandbox's: namespace af = capsule::screen::affine).
CPP_NAMESPACE = "af"
## Prefix of an exported animation's C++ name ("spin" -> kSpinAffine).
CPP_PREFIX = "k"
## Suffix of an exported animation's C++ name.
CPP_SUFFIX = "Affine"
## Suffix of its one-animation table's C++ name.
CPP_TABLE_SUFFIX = "Table"
## Longest line export_cpp() writes on one line (the project's line length).
CPP_LINE_LENGTH = 120
## Indent of a command on a line of its own (3 spaces).
CPP_INDENT = "   "


class AffineError(ValueError):
   """!An animation file that cannot be read or written."""


# -- the engine's numbers ----------------------------------------------------------------------------------------

def _header_text(header: str) -> str:
   """!An engine header's text, or "" without an engine checkout.
   @param header  path below include/
   @return its text
   """
   try:
      return (engine.root() / "include" / header).read_text(encoding="utf-8")
   except (OSError, engine.EngineNotFound):
      return ""


def _constant(text: str, name: str, fallback: int) -> int:
   """!An integer constant (decimal or hex) of a header's text.
   @param text      the header
   @param name      the constant's name
   @param fallback  its value when it is missing
   @return the value
   """
   m = re.search(r"\b" + re.escape(name) + r"\s*=\s*(0[xX][0-9a-fA-F]+|\d+)", text)
   return int(m.group(1), 0) if m else fallback


@dataclass(frozen=True)
class EngineNumbers:
   """!The constants and the sine table the engine's affine step uses (read from its headers)."""

   ## Cmd::a of a Loop.
   type_loop: int
   ## Cmd::a of a Jump.
   type_jump: int
   ## Cmd::a of an End.
   type_end: int
   ## Scale 1.0, 8.8.
   scale_one: int
   ## Fractional bits of a Q14 value.
   q14_shift: int
   ## sin(i * 90 / 64 degrees) in Q14, i = 0..64 (trig.h kQuarterSineQ14).
   quarter_sine: tuple[int, ...]

   def sin_q14(self, angle: int) -> int:
      """!The engine's sin_q14() (trig.h): the angle's top 8 bits through the quarter-wave table.
      @param angle  16-bit turn
      @return sine, Q14
      """
      step = (angle & (WORD_VALUES - 1)) >> ROTATION_SHIFT
      quadrant = step >> QUADRANT_SHIFT
      i = step & QUARTER_STEP_MASK
      v = self.quarter_sine[QUARTER_STEPS - i] if quadrant & 1 else self.quarter_sine[i]
      return -v if quadrant >= NEGATIVE_QUADRANT else v

   def cos_q14(self, angle: int) -> int:
      """!The engine's cos_q14(): sin of the angle plus a quarter turn.
      @param angle  16-bit turn
      @return cosine, Q14
      """
      return self.sin_q14((angle + QUARTER_TURN) & (WORD_VALUES - 1))


## Cached EngineNumbers once read.
_numbers: EngineNumbers | None = None


def numbers() -> EngineNumbers:
   """!The engine's affine constants and sine table (read once from its headers).
   @return EngineNumbers
   @throws AffineError when trig.h's table cannot be read (no engine checkout)
   """
   global _numbers
   if _numbers is None:
      affine = _header_text(AFFINE_HEADER)
      trig = _header_text(TRIG_HEADER)
      m = re.search(r"kQuarterSineQ14\[\d+\]\s*=\s*\{([^}]*)\}", trig)
      if m is None:
         raise AffineError("the engine's sine table (include/" + TRIG_HEADER + ") cannot be read")
      table = tuple(int(v) for v in re.findall(r"-?\d+", m.group(1)))
      if len(table) != QUARTER_STEPS + 1:
         raise AffineError(f"the engine's sine table has {len(table)} entries, not {QUARTER_STEPS + 1}")
      _numbers = EngineNumbers(_constant(affine, "kTypeLoop", FALLBACK_TYPE_LOOP),
                               _constant(affine, "kTypeJump", FALLBACK_TYPE_JUMP),
                               _constant(affine, "kTypeEnd", FALLBACK_TYPE_END),
                               _constant(affine, "kScaleOne", FALLBACK_SCALE_ONE),
                               _constant(trig, "kQ14Shift", FALLBACK_Q14_SHIFT), table)
   return _numbers


def s16(v: int) -> int:
   """!A value kept to a signed 16-bit word (C++'s static_cast<int16_t>).
   @param v  the value
   @return -32768 to 32767
   """
   v &= WORD_VALUES - 1
   return v - WORD_VALUES if v > S16_MAX else v


def c_div(a: int, b: int) -> int:
   """!C's integer division (toward zero).
   @param a  dividend
   @param b  divisor (not 0)
   @return the quotient
   """
   q = abs(a) // abs(b)
   return q if (a >= 0) == (b >= 0) else -q


def inverse_scale(scale: int) -> int:
   """!affine.h inverse_scale(): 0x10000 / scale kept to 16 bits (0 for 0).
   @param scale  8.8
   @return the inverse, 8.8
   """
   return 0 if scale == 0 else s16(c_div(ONE_SQUARED, scale))


@dataclass(frozen=True)
class Matrix:
   """!An OBJ matrix (8.8): texture dx / dy per screen x / y."""

   ## Texture dx per screen x.
   pa: int
   ## Texture dx per screen y.
   pb: int
   ## Texture dy per screen x.
   pc: int
   ## Texture dy per screen y.
   pd: int


def rotation_scaling(x_inverse: int, y_inverse: int, rotation: int) -> Matrix:
   """!The engine's matrix rule (affine.cpp rotation_scaling()).
   @param x_inverse  0x10000 / x scale
   @param y_inverse  0x10000 / y scale
   @param rotation   16-bit turn
   @return the matrix
   """
   n = numbers()
   sin, cos = n.sin_q14(rotation), n.cos_q14(rotation)
   return Matrix(s16((x_inverse * cos) >> n.q14_shift), s16((-x_inverse * sin) >> n.q14_shift),
                 s16((y_inverse * sin) >> n.q14_shift), s16((y_inverse * cos) >> n.q14_shift))


# -- commands ----------------------------------------------------------------------------------------------------

@dataclass
class Cmd:
   """!One command as the engine stores it: a, b (s16), c, d (u8)."""

   ## Frame: x scale change; else the kind's type value.
   a: int
   ## Frame: y scale change; Loop: count; Jump: command index.
   b: int
   ## Frame: rotation change (a byte: 0xFF is -1).
   c: int
   ## Frame: duration.
   d: int


def to_cmd(entry: dict[str, Any]) -> Cmd:
   """!A file's command as the engine's four fields.
   @param entry  {"op": ..., ...}
   @return Cmd
   @throws AffineError for an unknown kind or a value out of its field's range
   """
   n = numbers()
   op = entry.get("op")
   try:
      if op == OP_FRAME:
         xs, ys = int(entry.get("x_scale", 0)), int(entry.get("y_scale", 0))
         rot, dur = int(entry.get("rotation", 0)), int(entry.get("duration", 0))
         for name, v, low, high in (("x_scale", xs, S16_MIN, S16_MAX), ("y_scale", ys, S16_MIN, S16_MAX),
                                    ("rotation", rot, S8_MIN, S8_MAX), ("duration", dur, 0, U8_MAX)):
            if not low <= v <= high:
               raise AffineError(f"frame {name} {v} is outside {low} to {high}")
         if xs in (n.type_loop, n.type_jump, n.type_end):
            raise AffineError(f"frame x_scale {xs:#x} is a command type value")
         return Cmd(xs, ys, rot & U8_MAX, dur)
      if op == OP_LOOP:
         count = int(entry.get("count", 0))
         if not 0 <= count <= U8_MAX:
            raise AffineError(f"loop count {count} is outside 0 to {U8_MAX}")
         return Cmd(n.type_loop, count, 0, 0)
      if op == OP_JUMP:
         target = int(entry.get("target", 0))
         if not 0 <= target <= U8_MAX:
            raise AffineError(f"jump target {target} is outside 0 to {U8_MAX}")
         return Cmd(n.type_jump, target, 0, 0)
      if op == OP_END:
         return Cmd(n.type_end, 0, 0, 0)
   except (TypeError, ValueError) as e:
      if isinstance(e, AffineError):
         raise
      raise AffineError(f"{op}: {e}") from e
   raise AffineError(f"unknown command {op!r} (one of {', '.join(OPS)})")


def frame(x_scale: int = 0, y_scale: int = 0, rotation: int = 0, duration: int = 0) -> dict[str, Any]:
   """!A frame command as the file writes it.
   @param x_scale   x scale change (8.8; duration 0: the x scale)
   @param y_scale   y scale change
   @param rotation  rotation change, 1/256 turns
   @param duration  frames (0: set at once)
   @return the entry
   """
   return {"op": OP_FRAME, "x_scale": x_scale, "y_scale": y_scale, "rotation": rotation, "duration": duration}


def loop(count: int = 0) -> dict[str, Any]:
   """!A loop command (0: the loop's start marker).
   @param count  repeats
   @return the entry
   """
   return {"op": OP_LOOP, "count": count}


def jump(target: int = 0) -> dict[str, Any]:
   """!A jump command.
   @param target  command index
   @return the entry
   """
   return {"op": OP_JUMP, "target": target}


def end() -> dict[str, Any]:
   """!The end command.
   @return the entry
   """
   return {"op": OP_END}


def default_entry(op: str) -> dict[str, Any]:
   """!A new command of a kind, as the editor adds it.
   @param op  one of OPS
   @return the entry
   """
   return {OP_FRAME: frame, OP_LOOP: loop, OP_JUMP: jump, OP_END: end}[op]()


def sample() -> dict[str, Any]:
   """!A new file's animations (simple shapes: the engine sandbox's spin, pulse and squash).
   @return the file's data
   """
   try:
      one = numbers().scale_one
   except AffineError:
      one = FALLBACK_SCALE_ONE
   return {"schema": SCHEMA, "anims": [
      {"name": "spin", "cmds": [frame(0, 0, SAMPLE_SPIN_STEP, 1), jump(0)]},
      {"name": "pulse", "cmds": [frame(one, one), loop(0),
                                 frame(SAMPLE_PULSE_STEP, SAMPLE_PULSE_STEP, 0, SAMPLE_PULSE_FRAMES),
                                 frame(-SAMPLE_PULSE_STEP, -SAMPLE_PULSE_STEP, 0, SAMPLE_PULSE_FRAMES),
                                 loop(SAMPLE_PULSE_REPEATS), end()]},
      {"name": "squash", "cmds": [frame(one, one),
                                  frame(-SAMPLE_SQUASH_STEP, SAMPLE_SQUASH_STEP, 0, SAMPLE_SQUASH_FRAMES),
                                  frame(SAMPLE_SQUASH_STEP, -SAMPLE_SQUASH_STEP, 0, SAMPLE_SQUASH_FRAMES),
                                  jump(1)]},
   ]}


# -- the file ----------------------------------------------------------------------------------------------------

def check_data(data: dict[str, Any]) -> list[str]:
   """!The problems of a file's data (schema, names, every command's fields, jump targets inside the list).
   @param data  the file's data
   @return problem texts (empty: good)
   """
   out: list[str] = []
   if data.get("schema") != SCHEMA:
      out.append(f"schema is {data.get('schema')!r}, not {SCHEMA!r}")
   anims = data.get("anims")
   if not isinstance(anims, list):
      return out + ["'anims' is not a list"]
   seen: set[str] = set()
   for i, a in enumerate(anims):
      name = a.get("name") if isinstance(a, dict) else None
      if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
         out.append(f"animation {i}: name {name!r} is not an identifier")
      elif name in seen:
         out.append(f"animation {i}: name {name!r} is used twice")
      seen.add(str(name))
      cmds = a.get("cmds") if isinstance(a, dict) else None
      if not isinstance(cmds, list) or not cmds:
         out.append(f"{name}: no commands")
         continue
      for j, entry in enumerate(cmds):
         try:
            to_cmd(entry)
         except AffineError as e:
            out.append(f"{name} command {j}: {e}")
            continue
         if entry.get("op") == OP_JUMP and int(entry.get("target", 0)) >= len(cmds):
            out.append(f"{name} command {j}: jump to {entry.get('target')}, past the last command")
      last = cmds[-1].get("op") if isinstance(cmds[-1], dict) else None
      if last not in (OP_END, OP_JUMP):
         out.append(f"{name}: the last command is {last!r}: an animation ends with end or jump")
   return out


def write_if_changed(path: Path, text: str) -> bool:
   """!Writes a text with LF line ends, only when its bytes change, creating its folder (the release's generator
   rule).
   @param path  the file
   @param text  its text
   @return True when the file was written
   """
   data = text.replace("\r\n", "\n").encode("utf-8")
   if path.is_file() and path.read_bytes() == data:
      return False
   path.parent.mkdir(parents=True, exist_ok=True)
   path.write_bytes(data)
   return True


def cpp_name(name: str, table: bool = False) -> str:
   """!An animation's C++ name ("spin" -> kSpinAffine; its table kSpinAffineTable).
   @param name   the animation's name
   @param table  the one-animation table's name
   @return identifier
   """
   camel = "".join(part[:1].upper() + part[1:] for part in name.split("_") if part)
   return CPP_PREFIX + camel + CPP_SUFFIX + (CPP_TABLE_SUFFIX if table else "")


def _cpp_cmd(entry: dict[str, Any]) -> str:
   """!One command as the engine's constexpr helpers write it.
   @param entry  the file's command
   @return C++ text
   """
   op = entry["op"]
   if op == OP_FRAME:
      return (f"{CPP_NAMESPACE}::frame({int(entry.get('x_scale', 0))}, {int(entry.get('y_scale', 0))}, "
              f"{int(entry.get('rotation', 0))}, {int(entry.get('duration', 0))})")
   if op == OP_LOOP:
      return f"{CPP_NAMESPACE}::loop({int(entry.get('count', 0))})"
   if op == OP_JUMP:
      return f"{CPP_NAMESPACE}::jump({int(entry.get('target', 0))})"
   return f"{CPP_NAMESPACE}::end()"


def export_cpp(data: dict[str, Any], source: str = "") -> str:
   """!The animations as C++ for a game's sources: each one an `af::Cmd` array and a one-animation table
   (`const af::Cmd* const`), the form sprite templates take (anim::SpriteTemplate::affine_anims).
   @param data    the file's data (check_data() good)
   @param source  the file's name for the header comment, posix and relative ("" for none)
   @return the text (LF line ends)
   @throws AffineError when the data has problems
   """
   found = check_data(data)
   if found:
      raise AffineError("; ".join(found))
   lines = ["// Generated by the Studio's affine animation editor" + (f" from {source}" if source else "") +
            ": do not edit.",
            "// Include it where `namespace " + CPP_NAMESPACE + " = capsule::screen::affine;` is in scope.",
            "#pragma once", ""]
   for a in data["anims"]:
      head = f"inline constexpr {CPP_NAMESPACE}::Cmd {cpp_name(a['name'])}[] = {{"
      body = ", ".join(_cpp_cmd(e) for e in a["cmds"])
      lines.append(f"/// Affine animation {a['name']} ({len(a['cmds'])} commands).")
      if len(head) + len(body) + len("};") <= CPP_LINE_LENGTH:
         lines.append(head + body + "};")
      else:   # one command a line, indented
         lines.append(head)
         lines += [CPP_INDENT + _cpp_cmd(e) + "," for e in a["cmds"]]
         lines.append("};")
      lines.append(f"/// Its table (a sprite template's affine animations).")
      lines.append(f"inline constexpr const {CPP_NAMESPACE}::Cmd* {cpp_name(a['name'], True)}[] = "
                   f"{{{cpp_name(a['name'])}}};")
      lines.append("")
   return "\n".join(lines)


# -- simulation ----------------------------------------------------------------------------------------------------

@dataclass
class Step:
   """!The state after one affine step (affine.h State, its matrix and the sprite's flags)."""

   ## The step (1: the first, at the sprite's creation).
   step: int
   ## The command the state points at.
   cmd: int
   ## Frames left of it.
   delay: int
   ## Loop repeats left.
   loop: int
   ## X scale, 8.8.
   x_scale: int
   ## Y scale, 8.8.
   y_scale: int
   ## Rotation, 16-bit turn.
   rotation: int
   ## The matrix set this step.
   matrix: Matrix
   ## The sprite's affine_ended.
   ended: bool
   ## A problem the engine would not report (data read past the list, a loop that never reaches a frame), or "".
   problem: str = ""


@dataclass
class _State:
   """!The engine's per-matrix state while simulating."""

   ## The command it points at.
   cmd: int = 0
   ## Frames left of it.
   delay: int = 0
   ## Loop repeats left.
   loop: int = 0
   ## X scale, 8.8.
   x_scale: int = 0
   ## Y scale, 8.8.
   y_scale: int = 0
   ## Rotation, 16-bit turn.
   rotation: int = 0
   ## The matrix last set (None before the first step).
   matrix: Matrix | None = None
   ## The sprite's affine_ended.
   ended: bool = False
   ## Same-step commands followed so far.
   chain: int = 0
   ## The first problem met, or "".
   problem: str = ""


class _PastEnd(Exception):
   """!The step read a command past the list (the engine would read whatever follows it)."""


class _Simulator:
   """!One animation's affine steps (affine.cpp, one matrix)."""

   def __init__(self, cmds: list[Cmd]) -> None:
      """!A fresh state (attach(): scale 1, no rotation).
      @param cmds  the animation's commands
      """
      ## The engine's numbers.
      self.n = numbers()
      ## The animation's commands.
      self.cmds = cmds
      ## The matrix's state.
      self.st = _State(x_scale=self.n.scale_one, y_scale=self.n.scale_one)
      ## The affine_beginning flag of the sprite (the next step begins the animation).
      self.beginning = True

   def at(self, index: int) -> Cmd:
      """!A command by its 8-bit index.
      @param index  the index
      @return the command
      @throws _PastEnd past the list
      """
      index &= U8_MAX
      if index >= len(self.cmds):
         raise _PastEnd(index)
      return self.cmds[index]

   def update(self, c: Cmd) -> None:
      """!add_and_update(): a frame's changes added, the matrix set.
      @param c  the frame
      @return None
      """
      st = self.st
      st.x_scale = s16(st.x_scale + c.a)
      st.y_scale = s16(st.y_scale + c.b)
      # the change is a whole step of the rotation's top byte; the low byte is cleared each time
      st.rotation = (st.rotation + (c.c << ROTATION_SHIFT)) & (WORD_VALUES - 1) & ~ROTATION_LOW_MASK
      st.matrix = rotation_scaling(inverse_scale(st.x_scale), inverse_scale(st.y_scale), st.rotation)

   def apply(self, c: Cmd) -> int:
      """!apply_frame(): with a duration its changes (one frame counted), without its values set at once.
      @param c  the frame
      @return the frames left to count
      """
      if c.d != 0:
         self.update(c)
         return c.d - 1
      self.st.x_scale, self.st.y_scale = s16(c.a), s16(c.b)
      self.st.rotation = (c.c << ROTATION_SHIFT) & (WORD_VALUES - 1)
      self.update(Cmd(0, 0, 0, 0))
      return 0

   def begin(self) -> None:
      """!begin_anim(): the first command applied as a frame (nothing when it is End).
      @return None
      """
      if self.at(0).a == self.n.type_end:
         return
      st = self.st
      st.cmd, st.delay, st.loop = 0, 0, 0
      self.beginning = False
      st.ended = False
      st.delay = self.apply(self.at(st.cmd))

   def walk_to_loop_top(self) -> None:
      """!jump_to_loop_top(): back to the command after the previous loop marker while repeats are left.
      @return None
      """
      st = self.st
      if st.loop == 0:
         return
      st.cmd = (st.cmd - 1) & U8_MAX
      while st.cmd != 0 and self.at(st.cmd - 1).a != self.n.type_loop:
         st.cmd = (st.cmd - 1) & U8_MAX
      st.cmd = (st.cmd - 1) & U8_MAX   # one before: the step's increment lands on the marker's next command

   def go_on(self) -> None:
      """!continue_anim(): counts the frame's duration, or runs the next command (loops go on in the same step).
      @return None
      """
      st = self.st
      st.chain += 1
      if st.chain > MAX_CHAIN:
         raise RecursionError
      if st.delay != 0:
         st.delay -= 1
         self.update(self.at(st.cmd))
         return
      st.cmd = (st.cmd + 1) & U8_MAX
      c = self.at(st.cmd)
      if c.a == self.n.type_loop:
         if st.loop != 0:
            st.loop -= 1
         else:
            st.loop = c.b & U8_MAX
         self.walk_to_loop_top()
         self.go_on()
      elif c.a == self.n.type_jump:
         st.cmd = c.b & U8_MAX
         st.delay = self.apply(self.at(st.cmd))
      elif c.a == self.n.type_end:
         st.ended = True
         st.cmd = (st.cmd - 1) & U8_MAX
         self.update(Cmd(0, 0, 0, 0))
      else:
         st.delay = self.apply(c)

   def step(self, number: int) -> Step:
      """!One affine step (affine.cpp step()).
      @param number  the number of the step, for the result
      @return the state after it
      """
      st, beginning = self.st, self.beginning
      st.chain = 0
      if not st.problem:
         try:
            if beginning:
               self.begin()
            else:
               self.go_on()
         except _PastEnd as e:
            st.problem = f"command {e.args[0]} is past the animation's {len(self.cmds)} commands"
         except RecursionError:
            st.problem = "the loop never reaches a frame (the engine would not return from this step)"
      matrix = st.matrix or rotation_scaling(inverse_scale(st.x_scale), inverse_scale(st.y_scale), st.rotation)
      return Step(number, st.cmd, st.delay, st.loop, st.x_scale, st.y_scale, st.rotation, matrix, st.ended,
                  st.problem)


def simulate(cmds: list[dict[str, Any]] | list[Cmd], steps: int = DEFAULT_STEPS) -> list[Step]:
   """!The states an animation goes through, one Step per affine step (see the module doc).
   @param cmds   the file's commands, or Cmds
   @param steps  steps to run
   @return Step list (step 1 first); after a problem every later step repeats the state it stopped in
   @throws AffineError for a command that is not valid
   """
   engine_cmds = [c if isinstance(c, Cmd) else to_cmd(c) for c in cmds]
   if not engine_cmds:
      raise AffineError("the animation has no commands")
   sim = _Simulator(engine_cmds)
   return [sim.step(i + 1) for i in range(steps)]


# -- the preview's sprite ------------------------------------------------------------------------------------------

## The preview's shapes (the engine sandbox's: a 32 x 32 ball with a ring and a top marker so turns show, a 16 x 16
## box with an edge and two halves): name -> side, pixels.
SHAPES = {"ball": 32, "box": 16}
## The ball's body radius and ring radius (squared bounds), and its marker's rows and half width.
BALL_RADIUS = 15
## The ball's ring: outside this radius.
RING_RADIUS = 9
## Top rows of the ball's marker.
MARKER_ROWS = 6
## Half width of the ball's marker.
MARKER_HALF_WIDTH = 3
## Colours (RGBA): the body, the ring, the marker, the box's edge, the box's halves, the double-size box's frame.
BODY = (224, 64, 48, 255)
## The ring's colour (and the box's right half).
RING_COLOR = (112, 32, 24, 255)
## The marker's colour.
MARKER = (255, 255, 255, 255)
## The box's edge colour.
EDGE = (248, 248, 0, 255)
## A clear pixel.
CLEAR = (0, 0, 0, 0)
## Bytes of an RGBA pixel.
RGBA_BYTES = 4
## Fractional bits of an 8.8 matrix entry.
FRACTION_BITS = 8
## Halves.
HALF = 2
## A double-size sprite's box is this many times its side.
DOUBLE = 2


def shape_pixel(shape: str, x: int, y: int) -> tuple[int, int, int, int]:
   """!A shape's texture pixel.
   @param shape  SHAPES name
   @param x      column (0 to side - 1)
   @param y      row
   @return RGBA (CLEAR outside the shape)
   """
   side = SHAPES[shape]
   half = side // HALF
   if shape == "box":
      if x in (0, side - 1) or y in (0, side - 1):
         return EDGE
      return BODY if x < half else RING_COLOR
   dx, dy = x - half, y - half
   r2 = dx * dx + dy * dy
   if r2 >= BALL_RADIUS * BALL_RADIUS:
      return CLEAR
   if y < MARKER_ROWS + 1 and -MARKER_HALF_WIDTH <= dx <= MARKER_HALF_WIDTH:
      return MARKER
   return RING_COLOR if r2 > RING_RADIUS * RING_RADIUS else BODY


def render_sprite(matrix: Matrix, shape: str = "ball", double: bool = True) -> tuple[int, int, bytes]:
   """!A sprite drawn through its matrix as the hardware draws an affine sprite: each pixel of its box (twice the
   side with double size) offset from the box's centre is taken to the texture by the matrix (8.8) and shows the
   texture pixel there, from the texture's centre; outside the texture it is clear.
   @param matrix  the matrix
   @param shape   SHAPES name
   @param double  double size (the box is twice the side; nothing of a grown or turned picture is cut off)
   @return (box width, box height, RGBA pixels)
   """
   side = SHAPES[shape]
   box = side * DOUBLE if double else side
   centre, half = box // HALF, side // HALF
   out = bytearray(box * box * RGBA_BYTES)
   at = 0
   for y in range(box):
      dy = y - centre
      for x in range(box):
         dx = x - centre
         tx = ((matrix.pa * dx + matrix.pb * dy) >> FRACTION_BITS) + half
         ty = ((matrix.pc * dx + matrix.pd * dy) >> FRACTION_BITS) + half
         if 0 <= tx < side and 0 <= ty < side:
            out[at:at + RGBA_BYTES] = bytes(shape_pixel(shape, tx, ty))
         at += RGBA_BYTES
   return box, box, bytes(out)
