"""![S8] Animation-script banks and a frame stepper for the Studio (M5, D-38; the engine's docs/ANIM_SCRIPT.md).

Banks are read with the engine's own tools/anim_bank.py (core.engine.tool()), so the Studio decodes exactly what the
engine's reader decodes: a `.canim` text is assembled first, a binary bank (`*.bin`, `*.canm`) is read as it is.

The Stepper runs a script the way the engine's player does (include/capsule/anim/player.h, src/anim/player.cpp):
run mode and wait mode, `frames_to_wait`, the call stack, the argument slots, the visual and sound counts that
`wait_visual`, `wait_sound` and `end` wait for, and the player's errors (bad operand, call depth, runaway). What
the player leaves to the game is modelled by settings, never guessed:

  - a sprite, visual task or sound task a script makes finishes after a number of frames (Lifetime: a fixed count,
    or one of the argument slots the command just set); it is finished in the sprite / task step after frame() of
    the frame that many frames after the one it was made in (the step that calls anim::finish_sprite() and friends);
  - `wait_sound` also waits while "sound busy" is set (the game's sound_busy hook), for that many frames;
  - a game command (opcode 0x40 and up) reads its operands and goes on, as a command whose behaviour is the game's;
    it is shown on the timeline's "game" lane.

Each frame's state is kept (FrameState), and every command run and every visual is put on a lane of the timeline
(TimelineEvent, Visual): sprites, tasks, sound, background (layers, scroll, colour effects, graphics) and control.
Nothing here needs Qt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from . import engine

## Folder of the engine's animation sandbox, below the engine root (simple shapes; BF's scenes).
SANDBOX_DIR = Path("apps") / "sandbox_anim"
## The sandbox's animation script, below SANDBOX_DIR.
SANDBOX_BANK = Path("data") / "shapes.canim"
## Suffix of an animation script text (assembled before it is read).
TEXT_SUFFIX = ".canim"

## Calls a script may nest (player.h kCallDepth).
CALL_DEPTH = 4
## Argument slots (bank.h kMaxArgs).
MAX_ARGS = 8
## Commands one frame may run before the player stops (player.h kMaxCommandsPerFrame).
MAX_COMMANDS_PER_FRAME = 1024
## frames_to_wait of a `delay 0` (player.cpp kWaitAsOne: the wait mode's shortest step).
WAIT_AS_ONE = -1
## Layers a bg_show / bg_scroll may name (hal::video::kNumBgs).
NUM_BGS = 4
## Colour effect modes set_blend takes (hal::video::BlendMode: off, alpha, brighten, darken).
NUM_BLEND_MODES = 4
## A delay n's next command runs n + this many frames later (the frame that ends wait mode, then the next one).
DELAY_EXTRA_FRAMES = 2
## Frames a Stepper runs at most when none is given (ten seconds at 60 Hz).
DEFAULT_MAX_FRAMES = 600
## Frames a visual lives when its symbol has no Lifetime.
DEFAULT_LIFETIME = 30
## Frames a sound counts as busy after play_se when "sound busy" is on and nothing else is said.
DEFAULT_SOUND_BUSY = 0

## Timeline lanes, top to bottom.
LANES = ("sprites", "tasks", "sound", "bg", "control", "game")
## Lane of each generic command (by name).
COMMAND_LANES = {
   "create_sprite": "sprites", "create_task": "tasks", "create_sound_task": "sound", "play_se": "sound",
   "wait_sound": "sound", "load_gfx": "bg", "unload_gfx": "bg", "set_blend": "bg", "blend_off": "bg",
   "bg_show": "bg", "bg_scroll": "bg",
}

## Player errors (player.h PlayerError), as the timeline names them.
ERROR_BAD_OPERAND = "bad operand"
## The player's BadOpcode.
ERROR_BAD_OPCODE = "bad opcode"
## The player's BadScript.
ERROR_BAD_SCRIPT = "bad script"
## The player's CallDepth.
ERROR_CALL_DEPTH = "call depth"
## The player's Runaway.
ERROR_RUNAWAY = "runaway"
## A run that reached its frame limit with the script still running.
ERROR_FRAME_LIMIT = "still running at the frame limit"

## Symbol kinds a visual can be (anim_bank KINDS index): sprite template, visual task, sound task.
KIND_TEMPLATE = 0
## A visual task symbol's kind.
KIND_TASK = 1
## A sound task symbol's kind.
KIND_SOUND_TASK = 2


class ScriptError(ValueError):
   """!A bank that cannot be read (the engine reader's BankError, or a file that cannot be read)."""


def bank_tool() -> ModuleType:
   """!The engine's tools/anim_bank.py.
   @return the module
   @throws engine.EngineNotFound when no engine checkout is found
   """
   return engine.tool("anim_bank")


def sandbox_bank() -> Path:
   """!The engine sandbox's animation script (simple shapes), the panel's sample.
   @return its path
   @throws engine.EngineNotFound when no engine checkout is found
   """
   return engine.root() / SANDBOX_DIR / SANDBOX_BANK


def load_bank(path: str | Path) -> Any:
   """!Reads a bank: a .canim text is assembled first (the engine's assembler), anything else is read as bytes.
   @param path  the file
   @return anim_bank.Bank
   @throws ScriptError when it cannot be read, assembled or decoded
   """
   tool = bank_tool()
   path = Path(path)
   try:
      if path.suffix.lower() == TEXT_SUFFIX:
         data = tool.assemble(path.read_text(encoding="utf-8"))
      else:
         data = path.read_bytes()
      return tool.read_bank(data)
   except (OSError, UnicodeDecodeError, tool.BankError) as e:
      raise ScriptError(f"{path.name}: {e}") from e


def listing(bank: Any) -> list[Any]:
   """!Every command of a bank's code, in order (the engine reader's decode()).
   @param bank  anim_bank.Bank
   @return anim_bank.Command list
   @throws ScriptError when the code does not decode
   """
   tool = bank_tool()
   try:
      return tool.commands(bank)
   except tool.BankError as e:
      raise ScriptError(str(e)) from e


def problems(bank: Any) -> list[str]:
   """!The bank's problems (the engine reader's check_bank(): addresses, symbols, indices).
   @param bank  anim_bank.Bank
   @return problem texts (empty: good)
   """
   return list(bank_tool().check_bank(bank))


def operand_text(bank: Any, letter: str, value: int | list[int]) -> str:
   """!One operand as the disassembler writes it (symbols by name, argument lists in brackets).
   @param bank    anim_bank.Bank
   @param letter  its signature letter
   @param value   its value
   @return text
   """
   tool = bank_tool()
   if letter == tool.ARGS:
      return "[" + ", ".join(str(v) for v in value) + "]"
   if letter == tool.ADDRESS:
      return f"@{value:#06x}"
   if letter in tool.KIND_LETTERS and isinstance(value, int) and value < len(bank.symbols):
      return f"{letter}:{bank.symbols[value][tool.SYMBOL_NAME_FIELD]}"
   return str(value)


def command_text(bank: Any, command: Any) -> str:
   """!A command's operands as text.
   @param bank     anim_bank.Bank
   @param command  anim_bank.Command
   @return text (empty for none)
   """
   return " ".join(operand_text(bank, letter, value) for letter, value in zip(command.signature, command.operands))


@dataclass
class Lifetime:
   """!How long a visual of one symbol lives (the code of the game decides; this is a setting of the stepper)."""

   ## Frames, when from_arg is None.
   frames: int = DEFAULT_LIFETIME
   ## The argument slot whose value (after the command set the arguments) is the frame count, or None.
   from_arg: int | None = None
   ## Frames added to the value of the argument (a callback that counts the argument down from its creation call
   ## finishes one frame sooner: -1).
   offset: int = 0

   def frames_for(self, args: list[int]) -> int:
      """!The frames a visual made with these arguments lives (at least 1).
      @param args  the argument slots of the player after the command
      @return frames
      """
      arg, offset, frames = self.from_arg, self.offset, self.frames
      if arg is not None and 0 <= arg < len(args):
         return max(1, args[arg] + offset)
      return max(1, frames)


## The engine sandbox's lifetimes (apps/sandbox_anim/src/scenes.cpp): the balls' callback and the orbit task count
## argument 2 down from their creation call (finished on the frame of the last count, one sooner than the
## argument); the flash task ramps 0 to 16 and back, each amount held two frames, the last one ending it.
SANDBOX_FLASH_FRAMES = 66
## The sandbox's argument slot with a visual's frame count.
SANDBOX_LIFE_ARG = 2
## The sandbox's Lifetime by symbol.
SANDBOX_LIFETIMES = {
   "ball": Lifetime(from_arg=SANDBOX_LIFE_ARG, offset=-1),
   "ghost": Lifetime(from_arg=SANDBOX_LIFE_ARG, offset=-1),
   "orbit": Lifetime(from_arg=SANDBOX_LIFE_ARG, offset=-1),
   "flash": Lifetime(frames=SANDBOX_FLASH_FRAMES),
}


@dataclass
class Visual:
   """!A sprite, visual task or sound task a script made."""

   ## "sprites", "tasks" or "sound".
   lane: str
   ## Its symbol's name.
   name: str
   ## Frame it was made in (1: the first frame()).
   made: int
   ## Frame whose step finishes it (None: still alive at the end of the run).
   finished: int | None
   ## Address of the command that made it.
   address: int


@dataclass
class TimelineEvent:
   """!One command run on one frame."""

   ## The frame (1: the first frame()).
   frame: int
   ## Its lane (LANES).
   lane: str
   ## The command's address.
   address: int
   ## The command's name.
   name: str
   ## Its operands as text.
   text: str
   ## What happened when it is more than running (waited, jumped, an error), or "".
   note: str = ""


@dataclass
class FrameState:
   """!The player after one frame (frame 0: just after start())."""

   ## The frame.
   frame: int
   ## Address of the next command.
   pc: int
   ## Wait mode.
   waiting: bool
   ## The player's frames_to_wait.
   frames_to_wait: int
   ## The script still runs.
   active: bool
   ## Argument slots.
   args: list[int]
   ## Return addresses, innermost last.
   stack: list[int]
   ## Visuals counted (sprites and visual tasks).
   visual_count: int
   ## Sound tasks counted.
   sound_count: int
   ## Addresses of the commands run this frame, in order.
   ran: list[int] = field(default_factory=list)
   ## The player's error, or "".
   error: str = ""


@dataclass
class _Player:
   """!The player's state while stepping (player.h Player, the fields the generic commands use)."""

   ## frame() calls since start().
   frame: int = 0
   ## Address of the next command.
   pc: int = 0
   ## Wait mode.
   waiting: bool = False
   ## The player's frames_to_wait.
   frames_to_wait: int = 0
   ## The script runs.
   active: bool = False
   ## The error that stopped it, or "".
   error: str = ""
   ## Argument slots.
   args: list[int] = field(default_factory=lambda: [0] * MAX_ARGS)
   ## Return addresses.
   stack: list[int] = field(default_factory=list)
   ## Visuals counted.
   visual_count: int = 0
   ## Sound tasks counted.
   sound_count: int = 0
   ## Frame before which wait_sound still waits for the sound (sound_busy).
   busy_until: int = 0
   ## Addresses of the commands run this frame.
   ran: list[int] = field(default_factory=list)


class Stepper:
   """!Runs one script of a bank frame by frame, as the engine's player does (see the module doc)."""

   def __init__(self, bank: Any, script: int = 0, lifetimes: dict[str, Lifetime] | None = None,
                default_lifetime: Lifetime | None = None, sound_busy: int = DEFAULT_SOUND_BUSY) -> None:
      """!Starts the script (frame 0).
      @param bank              anim_bank.Bank
      @param script            script index
      @param lifetimes         Lifetime by symbol name, or None
      @param default_lifetime  Lifetime of the others, or None for DEFAULT_LIFETIME frames
      @param sound_busy        frames wait_sound waits after each play_se
      """
      ## The anim_bank.Bank.
      self.bank = bank
      ## The script's index.
      self.script = script
      ## Lifetime by symbol name.
      self.lifetimes = dict(lifetimes or {})
      ## The Lifetime of a symbol without one.
      self.default_lifetime = default_lifetime or Lifetime()
      ## Frames wait_sound waits after each play_se (the game's sound_busy hook; 0: never busy).
      self.sound_busy = sound_busy
      ## The engine's tools/anim_bank.py.
      self._tool = bank_tool()
      ## Decoded commands by address.
      self._decoded = dict[int, Any]()
      ## FrameState per frame (index = frame).
      self.states = list[FrameState]()
      ## TimelineEvent list, in run order.
      self.events = list[TimelineEvent]()
      ## Visual list, in the order they were made.
      self.visuals = list[Visual]()
      ## The player's state (player.h Player).
      self._p = _Player()
      if 0 <= script < len(bank.scripts):
         self._p.pc = bank.scripts[script][1]
         self._p.active = True
      else:
         self._p.error = ERROR_BAD_SCRIPT
      self.states.append(self._snapshot())

   # -- running -----------------------------------------------------------------------------------------------

   @property
   def running(self) -> bool:
      """!Whether the script still runs.
      @return True while active
      """
      return self._p.active

   def step(self) -> FrameState:
      """!One frame: the player's frame(), then the sprite / task step that finishes visuals whose time is up.
      @return the frame's state
      """
      self._p.frame += 1
      self._p.ran = []
      if self._p.active:
         self._run_frame()
      self._finish_visuals()
      state = self._snapshot()
      self.states.append(state)
      return state

   def run(self, max_frames: int = DEFAULT_MAX_FRAMES) -> list[FrameState]:
      """!Steps until the script stops or max_frames frames ran (then ERROR_FRAME_LIMIT is noted on the last frame).
      @param max_frames  frame limit
      @return every frame's state
      """
      while self._p.active and self._p.frame < max_frames:
         self.step()
      if self._p.active:
         self.states[-1].error = ERROR_FRAME_LIMIT
      return self.states

   def _run_frame(self) -> None:
      """!The player's frame() (player.cpp): wait mode counts down, run mode runs commands until one waits.
      @return None
      """
      if self._p.waiting:
         # wait mode: the frame the count is used up only leaves it; commands run again the next frame
         if self._p.frames_to_wait <= 0:
            self._p.waiting = False
            self._p.frames_to_wait = 0
         else:
            self._p.frames_to_wait -= 1
         return
      run = 0
      while True:
         run += 1
         if run > MAX_COMMANDS_PER_FRAME:
            self._fail(ERROR_RUNAWAY, self._p.pc)
            return
         self._command()
         if self._p.frames_to_wait != 0 or not self._p.active:
            return

   def _decode(self, address: int) -> Any | None:
      """!The command at an address (cached), or None after failing the player.
      @param address  code address
      @return anim_bank.Command, or None
      """
      if address in self._decoded:
         return self._decoded[address]
      if address >= len(self.bank.code):
         self._fail(ERROR_BAD_OPERAND, address)
         return None
      if self.bank.signature(self.bank.code[address]) is None:
         self._fail(ERROR_BAD_OPCODE, address)
         return None
      try:
         command = self._tool.decode(self.bank, address)
      except self._tool.BankError:
         self._fail(ERROR_BAD_OPERAND, address)
         return None
      self._decoded[address] = command
      return command

   def _command(self) -> None:
      """!Runs the command at pc.
      @return None
      """
      c = self._decode(self._p.pc)
      if c is None:
         return
      self._p.ran.append(c.address)
      handler = getattr(self, "_op_" + c.name, None) if c.op < self._tool.FIRST_GAME_OPCODE else None
      if handler is None:
         self._advance(c)
         self._event(c, "game", "the game's command: its behaviour is the game's")
         return
      handler(c)

   # -- generic commands (player.cpp) ------------------------------------------------------------------------

   def _op_end(self, c: Any) -> None:
      """!end: waits while visuals or sound tasks run, then stops.
      @param c  the command
      @return None
      """
      if self._p.visual_count or self._p.sound_count:
         self._yield()
         self._event(c, "control", "waits for the visuals and sound tasks")
         return
      self._p.pc = c.address + c.size
      self._p.active = False
      self._event(c, "control", "the script ends")

   def _op_delay(self, c: Any) -> None:
      """!delay n: wait mode for n frames (0 counts as -1).
      @param c  the command
      @return None
      """
      self._advance(c)
      n = c.operands[0]
      self._p.waiting = True
      self._p.frames_to_wait = n if n != 0 else WAIT_AS_ONE
      self._event(c, "control", f"the next command runs {n + DELAY_EXTRA_FRAMES} frames later")

   def _op_wait_visual(self, c: Any) -> None:
      """!wait_visual: yields until no visual is counted.
      @param c  the command
      @return None
      """
      if self._p.visual_count:
         self._yield()
         self._event(c, "control", f"waits ({self._p.visual_count} visual)")
         return
      self._advance(c)
      self._p.frames_to_wait = 0
      self._event(c, "control")

   def _op_wait_sound(self, c: Any) -> None:
      """!wait_sound: yields while sound tasks run or the sound is busy.
      @param c  the command
      @return None
      """
      if self._p.sound_count or self._p.frame < self._p.busy_until:
         self._yield()
         self._event(c, "sound", "waits for the sound")
         return
      self._advance(c)
      self._p.frames_to_wait = 0
      self._event(c, "sound")

   def _op_jump(self, c: Any) -> None:
      """!jump a.
      @param c  the command
      @return None
      """
      self._advance(c)
      self._goto(c, c.operands[0], "control", "jumps")

   def _op_call(self, c: Any) -> None:
      """!call a: pushes the next command's address.
      @param c  the command
      @return None
      """
      self._advance(c)
      if len(self._p.stack) >= CALL_DEPTH:
         self._fail(ERROR_CALL_DEPTH, c.address)
         self._event(c, "control", ERROR_CALL_DEPTH)
         return
      self._p.stack.append(self._p.pc)
      self._goto(c, c.operands[0], "control", "calls")

   def _op_return(self, c: Any) -> None:
      """!return: pops the last call's address.
      @param c  the command
      @return None
      """
      if not self._p.stack:
         self._fail(ERROR_CALL_DEPTH, c.address)
         self._event(c, "control", "return without a call")
         return
      self._p.pc = self._p.stack.pop()
      self._event(c, "control", "returns")

   def _op_set_arg(self, c: Any) -> None:
      """!set_arg n v.
      @param c  the command
      @return None
      """
      self._advance(c)
      n, v = c.operands
      if n >= MAX_ARGS:
         self._fail(ERROR_BAD_OPERAND, c.address)
         self._event(c, "control", ERROR_BAD_OPERAND)
         return
      self._p.args[n] = v
      self._event(c, "control")

   def _op_jump_if_arg_eq(self, c: Any) -> None:
      """!jump_if_arg_eq n v a.
      @param c  the command
      @return None
      """
      self._advance(c)
      n, v, a = c.operands
      if n >= MAX_ARGS:
         self._fail(ERROR_BAD_OPERAND, c.address)
         self._event(c, "control", ERROR_BAD_OPERAND)
         return
      if self._p.args[n] == v:
         self._goto(c, a, "control", "jumps")
      else:
         self._event(c, "control", "goes on")

   def _op_create_sprite(self, c: Any) -> None:
      """!create_sprite T flags args: one visual.
      @param c  the command
      @return None
      """
      self._make(c, "sprites", KIND_TEMPLATE)

   def _op_create_task(self, c: Any) -> None:
      """!create_task K priority args: one visual.
      @param c  the command
      @return None
      """
      self._make(c, "tasks", KIND_TASK)

   def _op_create_sound_task(self, c: Any) -> None:
      """!create_sound_task S priority args: one sound task.
      @param c  the command
      @return None
      """
      self._make(c, "sound", KIND_SOUND_TASK)

   def _op_load_gfx(self, c: Any) -> None:
      """!load_gfx tag: the hook, then wait mode for one frame.
      @param c  the command
      @return None
      """
      self._advance(c)
      self._p.waiting = True
      self._p.frames_to_wait = 1
      self._event(c, "bg", "the next command runs 3 frames later")

   def _op_play_se(self, c: Any) -> None:
      """!play_se se pan.
      @param c  the command
      @return None
      """
      self._advance(c)
      if self.sound_busy:
         self._p.busy_until = self._p.frame + self.sound_busy
      self._event(c, "sound")

   def _op_set_blend(self, c: Any) -> None:
      """!set_blend mode first second eva evb.
      @param c  the command
      @return None
      """
      self._advance(c)
      if c.operands[0] >= NUM_BLEND_MODES:
         self._fail(ERROR_BAD_OPERAND, c.address)
         self._event(c, "bg", ERROR_BAD_OPERAND)
         return
      self._event(c, "bg")

   def _op_bg_show(self, c: Any) -> None:
      """!bg_show n on.
      @param c  the command
      @return None
      """
      self._layer_command(c)

   def _op_bg_scroll(self, c: Any) -> None:
      """!bg_scroll n x y.
      @param c  the command
      @return None
      """
      self._layer_command(c)

   def _layer_command(self, c: Any) -> None:
      """!A command whose first operand is a layer (checked against NUM_BGS).
      @param c  the command
      @return None
      """
      self._advance(c)
      if c.operands[0] >= NUM_BGS:
         self._fail(ERROR_BAD_OPERAND, c.address)
         self._event(c, "bg", ERROR_BAD_OPERAND)
         return
      self._event(c, "bg")

   # unload_gfx, blend_off and nop only advance
   def _op_unload_gfx(self, c: Any) -> None:
      """!unload_gfx tag.
      @param c  the command
      @return None
      """
      self._advance(c)
      self._event(c, "bg")

   def _op_blend_off(self, c: Any) -> None:
      """!blend_off.
      @param c  the command
      @return None
      """
      self._advance(c)
      self._event(c, "bg")

   def _op_nop(self, c: Any) -> None:
      """!nop.
      @param c  the command
      @return None
      """
      self._advance(c)
      self._event(c, "control")

   # -- helpers -----------------------------------------------------------------------------------------------

   def _advance(self, c: Any) -> None:
      """!pc to the next command (the command read its operands).
      @param c  the command
      @return None
      """
      self._p.pc = c.address + c.size

   def _yield(self) -> None:
      """!The player's yield(): the loop ends, the command runs again next frame.
      @return None
      """
      self._p.frames_to_wait = 1

   def _goto(self, c: Any, address: int, lane: str, verb: str) -> None:
      """!The player's jump(): an address past the code fails the player.
      @param c        the command
      @param address  the target
      @param lane     the event's lane
      @param verb     what the event says ("jumps", "calls")
      @return None
      """
      if address >= len(self.bank.code):
         self._fail(ERROR_BAD_OPERAND, c.address)
         self._event(c, lane, ERROR_BAD_OPERAND)
         return
      self._p.pc = address
      self._event(c, lane, f"{verb} to {address:#06x}")

   def _fail(self, error: str, address: int) -> None:
      """!Stops the player with an error.
      @param error    the error text
      @param address  where
      @return None
      """
      self._p.error = error
      self._p.active = False
      self._p.pc = address

   def _make(self, c: Any, lane: str, kind: int) -> None:
      """!A command that makes a visual: the arguments set, the visual counted and given its lifetime.
      @param c     the command
      @param lane  "sprites", "tasks" or "sound"
      @param kind  its symbol's kind
      @return None
      """
      self._advance(c)
      symbol, _flags, args = c.operands
      if symbol >= len(self.bank.symbols) or self.bank.symbols[symbol][0] != kind:
         self._fail(ERROR_BAD_OPERAND, c.address)
         self._event(c, lane, ERROR_BAD_OPERAND)
         return
      for i, v in enumerate(args):
         self._p.args[i] = v   # entries past the count keep their values
      name = self.bank.symbols[symbol][self._tool.SYMBOL_NAME_FIELD]
      life = self.lifetimes.get(name, self.default_lifetime).frames_for(self._p.args)
      self.visuals.append(Visual(lane, name, self._p.frame, self._p.frame + life, c.address))
      if lane == "sound":
         self._p.sound_count += 1
      else:
         self._p.visual_count += 1
      self._event(c, lane, f"lives {life} frames")

   def _finish_visuals(self) -> None:
      """!The sprite / task step: visuals whose frame came finish (anim::finish_sprite() and friends).
      @return None
      """
      for v in self.visuals:
         if v.finished == self._p.frame:
            if v.lane == "sound":
               self._p.sound_count = max(0, self._p.sound_count - 1)
            else:
               self._p.visual_count = max(0, self._p.visual_count - 1)

   def _event(self, c: Any, lane: str, note: str = "") -> None:
      """!Puts a command run on the timeline.
      @param c     the command
      @param lane  its lane
      @param note  what happened, or ""
      @return None
      """
      self.events.append(TimelineEvent(self._p.frame, lane, c.address, c.name, command_text(self.bank, c), note))

   def _snapshot(self) -> FrameState:
      """!The player now.
      @return FrameState
      """
      p = self._p
      return FrameState(p.frame, p.pc, p.waiting, p.frames_to_wait, p.active, list(p.args), list(p.stack),
                        p.visual_count, p.sound_count, list(p.ran), p.error)

   # -- after a run -------------------------------------------------------------------------------------------

   def alive_at(self, frame: int) -> list[Visual]:
      """!The visuals alive after a frame's step.
      @param frame  the frame
      @return visuals made on or before it and not finished by it
      """
      return [v for v in self.visuals if v.made <= frame and (v.finished is None or v.finished > frame)]

   def close_open_visuals(self) -> None:
      """!Marks visuals still alive at the end of the run as unfinished (finished None).
      @return None
      """
      for v in self.visuals:
         if v.finished is not None and v.finished > self._p.frame:
            v.finished = None


def run_script(bank: Any, script: int = 0, lifetimes: dict[str, Lifetime] | None = None,
               default_lifetime: Lifetime | None = None, sound_busy: int = DEFAULT_SOUND_BUSY,
               max_frames: int = DEFAULT_MAX_FRAMES) -> Stepper:
   """!Runs a script to its end (or max_frames) and returns the stepper with every frame's state.
   @param bank              anim_bank.Bank
   @param script            script index
   @param lifetimes         Lifetime by symbol name
   @param default_lifetime  Lifetime of the others
   @param sound_busy        frames wait_sound waits after each play_se
   @param max_frames        frame limit
   @return the Stepper
   """
   s = Stepper(bank, script, lifetimes, default_lifetime, sound_busy)
   s.run(max_frames)
   s.close_open_visuals()
   return s
