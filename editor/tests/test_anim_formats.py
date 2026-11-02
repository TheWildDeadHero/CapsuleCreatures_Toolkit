#!/usr/bin/env python3
"""![S8] The battle animation tools' core (M5, D-38): the animation-script stepper against the engine's own player
tests (tests/anim_tests.cpp on tests/data/anim/test_bank.canim: the frames its game command logs), the affine
simulation against the engine's affine tests (the same states, step by step), the affine file (checks, the C++
export, write_if_changed()), the scanline tables (the engine's wave rules) and the scene viewer's frames (a stand-in
viewer program; the engine's own capsule_anim_view too when CAPSULE_ANIM_VIEW names it)."""
from __future__ import annotations

import os
import stat
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capsule_studio.core import anim_affine as af  # noqa: E402
from capsule_studio.core import anim_scanline as sl  # noqa: E402
from capsule_studio.core import anim_scene as sc  # noqa: E402
from capsule_studio.core import anim_script as an  # noqa: E402
from capsule_studio.core import engine  # noqa: E402

try:
   engine.root()
   HAVE_ENGINE = True
except engine.EngineNotFound:
   HAVE_ENGINE = False


def engine_bank(name: str = "test_bank.canim") -> Path:
   """!A bank text of the engine's tests.
   @param name  its file name
   @return its path
   """
   return engine.root() / "tests" / "data" / "anim" / name


@unittest.skipUnless(HAVE_ENGINE, "no engine checkout (set CAPSULE_ENGINE)")
class ScriptStepperTests(unittest.TestCase):
   """!core.anim_script: the player's frames, as the engine's tests expect them."""

   @classmethod
   def setUpClass(cls) -> None:
      """!The engine's test bank.
      @return None
      """
      if not engine_bank().is_file():
         raise unittest.SkipTest("this engine has no animation player tests")
      cls.bank = an.load_bank(engine_bank())

   def script(self, name: str) -> int:
      """!A script's index by name.
      @param name  its name
      @return index
      """
      return [n for n, _a in self.bank.scripts].index(name)

   def marks(self, s: an.Stepper) -> list[int]:
      """!The frames the test's game command (mark) ran on.
      @param s  the run
      @return frames
      """
      return [e.frame for e in s.events if e.name == "mark"]

   def test_delays(self) -> None:
      """!delay 0 takes 2 frames, delay n n + 2, load_gfx 3 (anim_tests.cpp: marks on frames 1, 3, 8, 11).
      @return None
      """
      s = an.run_script(self.bank, self.script("delays"))
      self.assertEqual(self.marks(s), [1, 3, 8, 11])
      self.assertFalse(s.running)
      self.assertEqual(s.states[-1].error, "")

   def test_visual_and_sound_counts(self) -> None:
      """!wait_visual and wait_sound with the test's lifetimes (the square's callback and count_down [3]: finished on
      frame 3; beep [2]: made on frame 4, finished on 5): marks on frames 1, 4, 6; arguments past a list's count kept.
      @return None
      """
      lives = {"square": an.Lifetime(2), "count_down": an.Lifetime(2), "beep": an.Lifetime(1)}
      s = an.run_script(self.bank, self.script("visual"), lives)
      self.assertEqual(self.marks(s), [1, 4, 6])
      self.assertEqual(s.states[1].visual_count, 2)
      self.assertEqual(s.states[-1].args[:2], [2, 20])
      self.assertEqual([(v.lane, v.made, v.finished) for v in s.visuals],
                       [("sprites", 1, 3), ("tasks", 1, 3), ("sound", 4, 5)])

   def test_control_and_errors(self) -> None:
      """!call / return / jump_if_arg_eq in one frame; args_keep; runaway; call depth; a bad script index.
      @return None
      """
      s = an.run_script(self.bank, self.script("control"))
      self.assertEqual(len(s.states), 2)   # frame 0 and frame 1: everything ran in one frame
      self.assertEqual([e.text for e in s.events if e.name == "mark"], ["9", "6"])
      self.assertEqual(s.states[-1].stack, [])
      s = an.run_script(self.bank, self.script("args_keep"))
      self.assertEqual(s.states[1].args[:3], [4, 2, 3])
      self.assertEqual(an.run_script(self.bank, self.script("runaway")).states[-1].error, an.ERROR_RUNAWAY)
      self.assertEqual(an.run_script(self.bank, self.script("deep")).states[-1].error, an.ERROR_CALL_DEPTH)
      bad = an.Stepper(self.bank, len(self.bank.scripts))
      self.assertFalse(bad.running)
      self.assertEqual(bad.states[0].error, an.ERROR_BAD_SCRIPT)

   def test_lifetime_from_argument(self) -> None:
      """!A Lifetime read from an argument slot, with its offset; the frame limit is reported.
      @return None
      """
      self.assertEqual(an.Lifetime(from_arg=2, offset=-1).frames_for([0, 0, 100]), 99)
      self.assertEqual(an.Lifetime(7).frames_for([0, 0, 100]), 7)
      self.assertEqual(an.Lifetime(from_arg=0).frames_for([0]), 1)   # at least one frame
      s = an.run_script(self.bank, self.script("visual"), default_lifetime=an.Lifetime(50), max_frames=10)
      self.assertEqual(s.states[-1].error, an.ERROR_FRAME_LIMIT)
      self.assertTrue(all(v.finished is None for v in s.visuals))   # still alive at the end

   def test_sandbox_sample(self) -> None:
      """!The engine sandbox's script with its lifetimes: every visual ends, wait_visual passes, the script ends.
      @return None
      """
      bank = an.load_bank(an.sandbox_bank())
      s = an.run_script(bank, 0, an.SANDBOX_LIFETIMES)
      self.assertFalse(s.running)
      self.assertEqual(s.states[-1].error, "")
      self.assertEqual([(v.name, v.made, v.finished) for v in s.visuals],
                       [("ball", 4, 103), ("ghost", 4, 73), ("orbit", 4, 93), ("flash", 26, 92)])
      self.assertEqual(s.events[-1].name, "end")
      self.assertEqual(s.events[-1].frame, 104)
      self.assertEqual(an.problems(bank), [])
      self.assertIn("T:ball", an.command_text(bank, an.listing(bank)[1]))

   def test_bad_bank(self) -> None:
      """!A file that is no bank is refused with the engine reader's reason.
      @return None
      """
      with tempfile.TemporaryDirectory() as folder:
         bad = Path(folder) / "bad.bin"
         bad.write_bytes(b"nothing")
         with self.assertRaises(an.ScriptError):
            an.load_bank(bad)


@unittest.skipUnless(HAVE_ENGINE, "no engine checkout (set CAPSULE_ENGINE)")
class AffineTests(unittest.TestCase):
   """!core.anim_affine: the engine's affine step and matrix rule, the file and its export."""

   def test_engine_steps(self) -> None:
      """!anim_tests.cpp affine_commands(): the grow animation's states, step by step, and the jump animation.
      @return None
      """
      grow = [af.frame(0x100, 0x100), af.frame(0x20, 0, 4, 2), af.loop(0), af.frame(-0x10, 0x10, -1, 1),
              af.loop(2), af.end()]
      steps = af.simulate(grow, 8)
      want = [(0x100, 0x100, 0), (0x120, 0x100, 0x400), (0x140, 0x100, 0x800), (0x130, 0x110, 0x700),
              (0x120, 0x120, 0x600), (0x110, 0x130, 0x500), (0x110, 0x130, 0x500), (0x110, 0x130, 0x500)]
      self.assertEqual([(s.x_scale, s.y_scale, s.rotation) for s in steps], want)
      self.assertEqual((steps[1].delay, steps[2].delay), (1, 0))
      self.assertEqual((steps[4].loop, steps[5].loop), (2, 1))
      self.assertEqual([s.ended for s in steps], [False] * 6 + [True, True])
      self.assertEqual(steps[7].cmd, 4)
      spin = af.simulate([af.frame(0, 0, 8, 1), af.jump(0)], 3)
      self.assertEqual([s.rotation for s in spin], [0x800, 0x1000, 0x1800])

   def test_matrix_rule(self) -> None:
      """!inverse_scale() and the matrix rule as the engine's tests write them.
      @return None
      """
      self.assertEqual([af.inverse_scale(v) for v in (0x100, 0x200, 0, 0x110)], [0x100, 0x80, 0, 240])
      n = af.numbers()
      self.assertEqual((n.sin_q14(0), n.sin_q14(0x4000), n.sin_q14(0x8000), n.sin_q14(0xC000)),
                       (0, 1 << n.q14_shift, 0, -(1 << n.q14_shift)))
      m = af.rotation_scaling(0x100, 0x100, 0x4000)
      self.assertEqual((m.pa, m.pb, m.pc, m.pd), (0, -0x100, 0x100, 0))
      self.assertEqual(af.rotation_scaling(0x100, 0x100, 0), af.Matrix(0x100, 0, 0, 0x100))

   def test_problems_reported(self) -> None:
      """!Data the engine would read past is reported, not followed.
      @return None
      """
      steps = af.simulate([af.frame(0x100, 0x100), af.frame(0, 0, 1, 1)], 3)
      self.assertIn("past the animation", steps[-1].problem)
      with self.assertRaises(af.AffineError):
         af.simulate([{"op": "spin"}])
      with self.assertRaises(af.AffineError):
         af.to_cmd(af.frame(0, 0, 200, 1))   # a rotation change is a signed byte

   def test_file_and_export(self) -> None:
      """!The sample checks clean and exports C++ (LF, written only when it changes); bad data is refused.
      @return None
      """
      data = af.sample()
      self.assertEqual(af.check_data(data), [])
      text = af.export_cpp(data, "anims/shapes.affine.json")
      self.assertIn("inline constexpr af::Cmd kSpinAffine[] = {af::frame(0, 0, 4, 1), af::jump(0)};", text)
      self.assertIn("kSquashAffineTable[] = {kSquashAffine};", text)
      self.assertNotIn("\r", text)
      with tempfile.TemporaryDirectory() as folder:
         out = Path(folder) / "gen" / "affine.h"
         self.assertTrue(af.write_if_changed(out, text))
         self.assertFalse(af.write_if_changed(out, text))
         self.assertEqual(out.read_bytes(), text.encode("utf-8"))
      bad = {"schema": af.SCHEMA, "anims": [{"name": "x", "cmds": [af.frame(), af.jump(9)]},
                                            {"name": "x", "cmds": [af.frame()]}]}
      found = af.check_data(bad)
      self.assertTrue(any("past the last command" in p for p in found), found)
      self.assertTrue(any("used twice" in p for p in found), found)
      self.assertTrue(any("ends with end or jump" in p for p in found), found)
      with self.assertRaises(af.AffineError):
         af.export_cpp(bad)

   def test_render(self) -> None:
      """!The preview draws the texture through the matrix: identity shows the ball in the middle of its 2x box; a
      half-size scale (matrix 2.0) shrinks it.
      @return None
      """
      w, h, px = af.render_sprite(af.Matrix(0x100, 0, 0, 0x100), "ball", True)
      side = af.SHAPES["ball"]
      self.assertEqual((w, h), (side * af.DOUBLE, side * af.DOUBLE))

      def opaque(data: bytes) -> int:
         return sum(1 for i in range(af.RGBA_BYTES - 1, len(data), af.RGBA_BYTES) if data[i])

      full = opaque(px)
      small = opaque(af.render_sprite(af.Matrix(0x200, 0, 0, 0x200), "ball", True)[2])
      self.assertGreater(full, small * 3)
      self.assertEqual(af.render_sprite(af.Matrix(0x100, 0, 0, 0x100), "box", False)[0], af.SHAPES["box"])


@unittest.skipUnless(HAVE_ENGINE, "no engine checkout (set CAPSULE_ENGINE)")
class ScanlineTests(unittest.TestCase):
   """!core.anim_scanline: the engine's wave rules and the other tables."""

   def test_wave(self) -> None:
      """!Samples (sine x amplitude) / 256 with the engine's 8.8 sine, the start sample kept delay + 1 frames and
      back to the first after 256 / frequency, the base added, lines outside start..end left 0.
      @return None
      """
      e = sl.Effect(start_line=10, end_line=20, frequency=64, amplitude=200, delay=1, base=3)
      sine = sl.engine_sine()
      self.assertEqual(sine[64], (1 << af.numbers().q14_shift) >> sl.SINE_TO_Q8)
      self.assertEqual(sl.wave_offsets(e, 9), [0, 0, 1, 1, 2, 2, 3, 3, 0])
      t = sl.tables(e, 1)[0]
      self.assertEqual(len(t), sl.LINE_ENTRIES)
      self.assertEqual(t[9], 0)
      self.assertEqual(t[10], 3)                          # sample 0: sine 0
      self.assertEqual(t[11], 200 + 3)                    # sample 1: sine[64] = 256 -> 200
      self.assertEqual(sl.signed(t[13]), -200 + 3)        # sample 3: sine[192] = -256 (16-bit entry)
      self.assertEqual(t[20], 0)
      self.assertIn("frequency", " ".join(sl.Effect(frequency=0).problems()))

   def test_ramp_diamond_render(self) -> None:
      """!Weights a + (16 - a) << 8; the diamond's edges; every register renders a full screen.
      @return None
      """
      ramp = sl.tables(sl.Effect(register="blend", source="ramp"), 2)
      self.assertEqual(ramp[0][0], sl.BLEND_MAX << sl.WINDOW_LINE_SHIFT)
      self.assertEqual(ramp[1][0], 1 | ((sl.BLEND_MAX - 1) << sl.WINDOW_LINE_SHIFT))
      d = sl.tables(sl.Effect(register="win0_h", source="diamond", radius=10), 1)[0]
      cx, cy = sl.SCREEN_WIDTH // sl.HALF, sl.SCREEN_HEIGHT // sl.HALF
      self.assertEqual(d[cy], ((cx - 10) << sl.WINDOW_LINE_SHIFT) | (cx + 10))
      self.assertEqual(d[0], 0)
      for reg in sl.REGISTERS:
         table = sl.tables(sl.Effect(register=reg, source=sl.DEFAULT_SOURCE[reg]), 1)[0]
         self.assertEqual(len(sl.render(reg, table)), sl.SCREEN_WIDTH * sl.SCREEN_HEIGHT * sl.RGB_BYTES)


## A stand-in for capsule_anim_view: frame k's pixels are all k (BGR555), --check passes.
FAKE_VIEWER = textwrap.dedent("""\
   #!{python}
   import sys
   args = sys.argv[1:]
   if args == ["--check"]:
      print("scripts ended 2, player errors 0, scanline frames 360, frame hash 00000000")
      sys.exit(0)
   frames = [int(v) for v in args[args.index("--frames") + 1].split(",")]
   with open(args[args.index("--out") + 1], "wb") as out:
      for k in frames:
         out.write(bytes([k & 0xFF, (k >> 8) & 0x7F]) * (240 * 160))
   """)


class SceneTests(unittest.TestCase):
   """!core.anim_scene: the scenes from scenes.h, BGR555 to RGB, a viewer's frames."""

   def test_bgr555(self) -> None:
      """!Each 5-bit channel widened (c << 3 | c >> 2): red, green, blue and white.
      @return None
      """
      raw = bytes([0x1F, 0x00, 0xE0, 0x03, 0x00, 0x7C, 0xFF, 0x7F])
      self.assertEqual(sc.bgr555_to_rgb(raw), bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255]))

   @unittest.skipUnless(HAVE_ENGINE, "no engine checkout (set CAPSULE_ENGINE)")
   def test_scenes(self) -> None:
      """!The sandbox's four scenes, named from scenes.h's doc, 180 frames each.
      @return None
      """
      found = sc.scenes()
      self.assertEqual([s.name for s in found], ["affine", "scanline", "blend", "script"])
      self.assertEqual(found[1].first, found[0].frames + 1)
      self.assertEqual(sc.total_frames(), sum(s.frames for s in found))
      self.assertEqual(sc.scene_of(found[2].first).name, "blend")

   @unittest.skipIf(os.name == "nt", "the stand-in viewer is a script with a #! line")
   def test_viewer_frames(self) -> None:
      """!Frames are read a run at a time and kept; a missing program and a failed run are reported.
      @return None
      """
      with tempfile.TemporaryDirectory() as folder:
         prog = Path(folder) / sc.VIEWER_NAME
         prog.write_text(FAKE_VIEWER.format(python=sys.executable), encoding="utf-8")
         prog.chmod(prog.stat().st_mode | stat.S_IXUSR)
         v = sc.Viewer(prog)
         rgb = v.frame(5)
         self.assertEqual(len(rgb), sc.FRAME_WIDTH * sc.FRAME_HEIGHT * sc.RGB_BYTES)
         self.assertEqual(rgb[:sc.RGB_BYTES], sc.bgr555_to_rgb(bytes([5, 0])))
         self.assertIn(5 + sc.READ_AHEAD - 1, v.frames)   # read ahead in the same run
         self.assertEqual(v.check()[0], True)
         with self.assertRaises(sc.ViewerError):
            sc.Viewer(Path(folder) / "missing")
         prog.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
         with self.assertRaises(sc.ViewerError):
            sc.Viewer(prog).frame(1)

   @unittest.skipUnless(os.environ.get(sc.VIEWER_ENV), "CAPSULE_ANIM_VIEW does not name the engine's viewer")
   def test_engine_viewer(self) -> None:
      """!The engine's own capsule_anim_view: its check passes and frames of every scene differ.
      @return None
      """
      v = sc.Viewer(os.environ[sc.VIEWER_ENV])
      self.assertTrue(v.check()[0])
      pictures = {v.frame(s.first + s.frames // af.HALF) for s in sc.scenes()}
      self.assertEqual(len(pictures), len(sc.scenes()))


if __name__ == "__main__":
   unittest.main()
