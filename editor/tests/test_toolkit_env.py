#!/usr/bin/env python3
"""![C14b] Tests for toolkit/env.py's dependency groups: the optional "audio" group (Qt Multimedia from
PySide6-Addons) is pinned at the UI's PySide6 version and installed by setup and the audio tools; a failed install
of it warns, is remembered (a launch does not try again, setup does) and leaves status --check passing; a required
group's failure still stops. pip and the environment are stand-ins: nothing is downloaded or created."""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from unittest import mock

## Repository root.
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "toolkit"))
import env  # noqa: E402

## Exit status of a pip that worked.
PIP_OK = 0
## Exit status of a pip that failed.
PIP_FAILED = 1


class FakePip:
   """!Records the requirement files pip was asked to install and fails for the chosen ones.
   """

   def __init__(self, failing: set[str]) -> None:
      """!A pip stand-in.
      @param failing  group names whose install fails
      """
      ## Groups whose install fails.
      self.failing = failing
      ## Groups asked for, in order.
      self.asked: list[str] = []

   def __call__(self, cmd: list[str], *args: Any, **kwargs: Any) -> int:
      """!Runs "pip install -r FILE".
      @param cmd     the command
      @param args    unused
      @param kwargs  unused
      @return its exit status
      """
      requirements = Path(cmd[cmd.index("-r") + 1])
      group = next(g for g, path in env.GROUPS.items() if path == requirements)
      self.asked.append(group)
      return PIP_FAILED if group in self.failing else PIP_OK


class ToolkitEnvTests(unittest.TestCase):
   """!env.py's groups with a stand-in environment."""

   def setUp(self) -> None:
      """!A temporary environment folder with a state file, and no real pip or venv.
      @return None
      """
      self.tmp = tempfile.TemporaryDirectory()
      self.addCleanup(self.tmp.cleanup)
      patches = [mock.patch.dict(os.environ, {"CAPSULE_STUDIO_VENV": self.tmp.name}),
                 mock.patch.object(env, "create", lambda reset=False: env.save_state(env.load_state() or
                                                                                     {"groups": {}})),
                 mock.patch.object(env, "link_sources", lambda: None),
                 mock.patch.object(env, "healthy", lambda: True)]
      for p in patches:
         p.start()
         self.addCleanup(p.stop)

   def run_env(self, failing: set[str], *argv: str) -> tuple[int, FakePip, str]:
      """!Runs env.py's main with a pip stand-in.
      @param failing  groups whose install fails
      @param argv     the command line
      @return (exit status, the pip stand-in, what it printed)
      """
      pip = FakePip(failing)
      out = io.StringIO()
      with mock.patch.object(env.subprocess, "call", pip), redirect_stdout(out):
         status = env.main(list(argv))
      return status, pip, out.getvalue()

   def test_audio_group_pins_addons_at_the_ui_version(self) -> None:
      """!audio.txt pins PySide6-Addons at ui.txt's PySide6-Essentials version (they must match).
      @return None
      """
      ui = dict(line.split("==") for line in env.requirement_lines("ui"))
      audio = dict(line.split("==") for line in env.requirement_lines("audio"))
      self.assertEqual(audio, {"PySide6-Addons": ui["PySide6-Essentials"]})
      self.assertIn("audio", env.OPTIONAL)
      self.assertNotIn("core", env.OPTIONAL)
      self.assertNotIn("ui", env.OPTIONAL)

   def test_tools_that_play_audio_need_the_group(self) -> None:
      """!The audio editor and the studio take the audio group; the other editors and the command line do not.
      @return None
      """
      for tool, (_module, groups) in env.TOOLS.items():
         self.assertEqual("audio" in groups, tool in ("audio-editor", "studio"), tool)

   def test_setup_installs_every_group(self) -> None:
      """!setup installs core, ui and audio; --core-only only core.
      @return None
      """
      status, pip, _out = self.run_env(set(), "setup")
      self.assertEqual(status, 0)
      self.assertEqual(pip.asked, ["ui", "audio"])   # core has no packages
      self.assertEqual(self.run_env(set(), "status", "--check")[0], 0)

   def test_core_only_skips_the_editors(self) -> None:
      """!setup --core-only installs nothing of the UI or audio groups.
      @return None
      """
      _status, pip, _out = self.run_env(set(), "setup", "--core-only")
      self.assertEqual(pip.asked, [])

   def test_failed_audio_warns_and_is_remembered(self) -> None:
      """!A failed audio install warns, setup still succeeds, status --check passes, a launch does not retry it
      and setup does.
      @return None
      """
      status, pip, out = self.run_env({"audio"}, "setup")
      self.assertEqual(status, 0)
      self.assertEqual(pip.asked, ["ui", "audio"])
      self.assertIn("warning: the optional audio packages could not be installed", out)
      self.assertIn("system's player", out)
      self.assertEqual(env.load_state()["groups"]["audio"], env.FAILED_MARK + env.digest("audio"))
      status, _pip, out = self.run_env(set(), "status", "--check")
      self.assertEqual(status, 0)
      self.assertIn("install failed (optional", out)
      # a launch (ensure() without retry) skips it
      pip = FakePip(set())
      with mock.patch.object(env.subprocess, "call", pip), redirect_stdout(io.StringIO()):
         env.ensure(env.TOOLS["audio-editor"][1])
      self.assertEqual(pip.asked, [])
      # setup tries again
      _status, pip, _out = self.run_env(set(), "setup")
      self.assertEqual(pip.asked, ["audio"])
      self.assertEqual(env.load_state()["groups"]["audio"], env.digest("audio"))

   def test_changed_pins_retry_a_failed_group(self) -> None:
      """!A failure is remembered for its pins only: new pins make the next launch try again.
      @return None
      """
      self.run_env({"audio"}, "setup")
      state = env.load_state()
      state["groups"]["audio"] = env.FAILED_MARK + "an older digest"
      env.save_state(state)
      pip = FakePip(set())
      with mock.patch.object(env.subprocess, "call", pip), redirect_stdout(io.StringIO()):
         env.ensure(env.TOOLS["studio"][1])
      self.assertEqual(pip.asked, ["audio"])

   def test_failed_ui_still_stops(self) -> None:
      """!A required group's failure stops setup with an error (nothing optional about it).
      @return None
      """
      with self.assertRaises(SystemExit) as stop:
         self.run_env({"ui"}, "setup")
      self.assertIn("could not install the ui packages", str(stop.exception.code))

   def test_offline_without_wheels_skips_audio_only(self) -> None:
      """!Offline without a wheel folder the optional group is skipped with a note (the required ones stop).
      @return None
      """
      out = io.StringIO()
      with mock.patch.object(env.subprocess, "call", FakePip(set())), redirect_stdout(out):
         self.assertFalse(env.pip_install("audio", None, offline=True))
      self.assertIn("skipping the optional audio packages", out.getvalue())
      with self.assertRaises(SystemExit):
         env.pip_install("ui", None, offline=True)


if __name__ == "__main__":
   unittest.main()
