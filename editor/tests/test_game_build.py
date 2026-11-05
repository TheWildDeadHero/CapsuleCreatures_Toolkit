#!/usr/bin/env python3
"""!Tests of core.game_build and `capsule-studio build` (no Qt): the targets this computer builds, the steps of a
game's build (as ./build PRESET --game FOLDER), the toolchain checks, finding the result and an emulator, and running
steps."""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capsule_studio.cli.main import main  # noqa: E402
from capsule_studio.core import engine, game_build  # noqa: E402

## A game's project manifest for the tests.
MANIFEST = '{"schema": "capsule.project/1", "name": "demo"}'
## Exit status of a step made to fail.
FAIL_STATUS = 3


class GameBuildTests(unittest.TestCase):
   """!A game folder in a temporary directory; environment variables are set per test."""

   def setUp(self) -> None:
      """!Makes the game folder.
      @return None
      """
      ## Temporary root.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_build_"))
      ## The game's folder.
      self.game = self.root / "demo"
      (self.game / "reference").mkdir(parents=True)
      (self.game / "reference" / "project.json").write_text(MANIFEST, encoding="utf-8")

   def tearDown(self) -> None:
      """!Removes it.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def test_targets_follow_the_host(self) -> None:
      """!This computer first (its preset family), the GBA everywhere, the Dreamcast off Windows.
      @return None
      """
      with mock.patch.object(sys, "platform", "linux"):
         ids = [(t.target_id, t.debug_preset) for t in game_build.targets()]
         self.assertEqual(ids, [("desktop", "desktop-debug"), ("gba", "gba-debug"), ("dreamcast", "dc-debug")])
      with mock.patch.object(sys, "platform", "win32"):
         ts = game_build.targets()
         self.assertEqual([t.target_id for t in ts], ["desktop", "gba"])
         self.assertEqual((ts[0].release_preset, ts[0].output_suffix), ("windows-release", ".exe"))
         with self.assertRaises(KeyError):
            game_build.target("dreamcast")
      with mock.patch.object(sys, "platform", "darwin"):
         self.assertIn("macOS", game_build.host_target().title)

   def test_plan_mirrors_the_build_script(self) -> None:
      """!Configure from the engine's folder into FOLDER/build/PRESET with the game in CAPSULE_GAMES, then build.
      @return None
      """
      build = game_build.plan(self.game / "reference" / "project.json", "gba", debug=True)
      self.assertEqual((build.name, build.preset), ("demo", "gba-debug"))
      self.assertEqual(build.out, self.game.resolve() / "build" / "gba-debug")
      configure, compile_ = build.steps
      self.assertEqual(configure.argv[:5], ["cmake", "--preset", "gba-debug", "-B", str(build.out)])
      self.assertIn(f"-DCAPSULE_GAMES={self.game.resolve()}", configure.argv)
      self.assertIn("-DCAPSULE_ENGINE_TESTS=OFF", configure.argv)
      self.assertEqual(compile_.argv, ["cmake", "--build", str(build.out)])
      self.assertEqual(configure.cwd, engine.root())
      self.assertIsNone(build.run)
      with self.assertRaises(ValueError):
         game_build.plan(self.root, "gba")
      self.assertEqual(len(game_build.plans(self.game, None)), len(game_build.targets()))

   def test_gba_toolchain_check(self) -> None:
      """!devkitARM, libgba and gbafix under DEVKITPRO; each missing one is named.
      @return None
      """
      kit = self.root / "devkitpro"
      with mock.patch.dict(os.environ, {"DEVKITPRO": str(kit)}):
         os.environ.pop("DEVKITARM", None)
         os.environ.pop("LIBGBA", None)
         missing = game_build.build_problems(game_build.GBA_TARGET)
         self.assertEqual(sum(1 for m in missing if "devkitARM" in m or "libgba" in m or "gbafix" in m), 3)
         for f in ("devkitARM/bin/arm-none-eabi-g++", "libgba/lib/libgba.a", "tools/bin/gbafix"):
            (kit / f).parent.mkdir(parents=True, exist_ok=True)
            (kit / f).write_text("", encoding="utf-8")
         missing = game_build.build_problems(game_build.GBA_TARGET)
         self.assertFalse([m for m in missing if "devkitARM" in m or "libgba" in m or "gbafix" in m], missing)
      with mock.patch.dict(os.environ, {"KOS_ENVIRON": str(self.root / "none.sh")}):
         self.assertTrue(any("KallistiOS" in m for m in game_build.build_problems(game_build.DREAMCAST_TARGET)))

   def test_outputs_and_emulators(self) -> None:
      """!The result is found (a Dreamcast .elf when there is no .cdi); emulators come from the environment first.
      @return None
      """
      out = self.root / "out"
      (out / "sub").mkdir(parents=True)
      self.assertIsNone(game_build.find_output(out, "demo", game_build.GBA_TARGET))
      (out / "sub" / "capsule_demo.gba").write_text("", encoding="utf-8")
      self.assertEqual(game_build.find_output(out, "demo", game_build.GBA_TARGET), out / "sub" / "capsule_demo.gba")
      (out / "capsule_demo.elf").write_text("", encoding="utf-8")
      self.assertEqual(game_build.find_output(out, "demo", game_build.DREAMCAST_TARGET), out / "capsule_demo.elf")
      with mock.patch.dict(os.environ, {game_build.GBA_EMULATOR_ENV: "my-mgba --fast"}):
         self.assertEqual(game_build.gba_emulator(), ["my-mgba", "--fast"])
         build = game_build.plan(self.game, "gba", debug=True, run=True)
         self.assertEqual(build.run.argv[:2], ["my-mgba", "--fast"])
         self.assertTrue(build.run.argv[-1].endswith("capsule_demo.gba"))
      with mock.patch.dict(os.environ, {game_build.DC_EMULATOR_ENV: "flycast"}):
         self.assertEqual(game_build.dreamcast_emulator(), ["flycast"])
      with mock.patch.object(game_build, "gba_emulator", return_value=None):
         build = game_build.plan(self.game, "gba", debug=True, run=True)
         self.assertIsNone(build.run)
         self.assertIn("mGBA", build.run_problem)
      native = game_build.plan(self.game, game_build.host_target().target_id, run=True, command=[])
      self.assertEqual(len(native.run.argv), 1)   # the executable starts itself

   def test_run_steps(self) -> None:
      """!Steps run in order with their output logged; the first that fails stops the rest.
      @return None
      """
      lines: list[str] = []
      ok = game_build.Step("Say", [sys.executable, "-c", "import os; print(os.environ['CAPSULE_TEST'])"], self.root,
                           {"CAPSULE_TEST": "hello"})
      bad = game_build.Step("Fail", [sys.executable, "-c", f"raise SystemExit({FAIL_STATUS})"], self.root)
      self.assertEqual(game_build.run_steps([ok, bad, ok], lines.append), FAIL_STATUS)
      self.assertEqual(lines.count("hello"), 1)
      self.assertIn("error: fail failed (exit status 3)", lines)
      lines.clear()
      self.assertEqual(game_build.run_steps([game_build.Step("Nothing", ["capsule-no-such-program"], self.root)],
                                            lines.append), 1)

   def test_command_line(self) -> None:
      """!build --list, --dry-run and the refusals.
      @return None
      """
      def run(*argv: str) -> tuple[int, str]:
         """!Runs the command line.
         @param argv  arguments
         @return exit status and output
         """
         out = io.StringIO()
         with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            status = main(list(argv))
         return status, out.getvalue()

      status, text = run("build", str(self.game), "--list")
      self.assertEqual(status, 0)
      self.assertIn("gba: Game Boy Advance (gba-debug / gba-release)", text)
      with mock.patch.object(game_build, "build_problems", return_value=[]):
         status, text = run("build", str(self.game), "--target", "gba", "--dry-run")
      self.assertEqual(status, 0)
      self.assertIn("cmake --preset gba-release", text)
      with mock.patch.object(game_build, "build_problems", return_value=["a thing"]):
         status, text = run("build", str(self.game), "--dry-run")
      self.assertEqual(status, 1)
      self.assertIn("missing: a thing", text)
      status, text = run("build", str(self.game), "--target", "all", "--run")
      self.assertEqual(status, 1)
      self.assertIn("pick one --target", text)
      status, text = run("build", str(self.game), "--target", "psp")
      self.assertEqual(status, 1)


if __name__ == "__main__":
   unittest.main()
