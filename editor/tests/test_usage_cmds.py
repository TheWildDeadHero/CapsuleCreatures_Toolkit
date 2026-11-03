"""!`capsule-studio usage` (cli/usage_cmds.py): a report found by file or by game name in a build folder, its summary
and JSON, the comparison with an nm listing, and the errors (no report, a file that is no report). The reports are
written with the engine's own tools/usage.py (the engine checkout in use)."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import engine  # noqa: E402

## The game the tests' report is of.
GAME = "demo"
## A symbol listing: one script symbol (used) and one sequence symbol (unused by the report).
NM = "08000000 00000030 T _ZN7capsule6script3runEv\n08000030 00000010 t _ZN7capsule3seq4tickEv\n"
## Exit status of a command error.
ERROR_STATUS = 1


def run_cli(*argv: object) -> tuple[int, str]:
   """!Runs the capsule-studio command line.
   @param argv  arguments
   @return (status, stdout + stderr)
   """
   out, err = io.StringIO(), io.StringIO()
   with redirect_stdout(out), redirect_stderr(err):
      status = cli([str(a) for a in argv])
   return status, out.getvalue() + err.getvalue()


class UsageCommandTests(unittest.TestCase):
   """!The usage command on a report the engine's tool merges."""

   def setUp(self) -> None:
      """!A build folder with one record merged into usage/demo.json."""
      try:
         self.tool = engine.tool("usage")
      except engine.EngineNotFound as e:
         self.skipTest(str(e))
      except ImportError:
         self.skipTest("the engine in use has no tools/usage.py")
      self.tmp = tempfile.TemporaryDirectory()
      self.build = Path(self.tmp.name)
      record = self.build / "usage" / GAME / "scripts.json"
      self.tool.write_record(record, GAME, "script", {"script.op": {"End": 2, "Message": 1}})
      self.report = self.build / "usage" / f"{GAME}.json"
      self.assertEqual(self.tool.main(["merge", str(record), "--game", GAME, "--out", str(self.report)]), 0)

   def tearDown(self) -> None:
      """!Removes the build folder."""
      self.tmp.cleanup()

   def test_by_name_and_file(self) -> None:
      """!A game's name in --build and the report's path print the same summary."""
      status, by_name = run_cli("usage", GAME, "--build", self.build)
      self.assertEqual(status, 0, by_name)
      self.assertIn("script.op: 2 used, 3 uses", by_name)
      self.assertIn("Engine modules used:", by_name)
      self.assertEqual(run_cli("usage", self.report), (0, by_name))

   def test_json(self) -> None:
      """!--json prints the report itself."""
      status, text = run_cli("usage", self.report, "--json")
      self.assertEqual(status, 0, text)
      self.assertEqual(json.loads(text)["used"], {"script.op": {"End": 2, "Message": 1}})

   def test_link(self) -> None:
      """!--link lists the modules linked while the report says nothing uses them."""
      listing = self.build / f"capsule_{GAME}.nm"
      listing.write_text(NM, encoding="utf-8")
      status, text = run_cli("usage", self.report, "--link", listing)
      self.assertEqual(status, 0, text)
      self.assertIn("seq: 16 B", text)
      status, text = run_cli("usage", self.report, "--link", listing, "--json")
      self.assertEqual(json.loads(text)["unused_linked"], ["seq"])

   def test_errors(self) -> None:
      """!No report for the name, and a file that is no report."""
      status, text = run_cli("usage", "nothing", "--build", self.build)
      self.assertEqual(status, ERROR_STATUS)
      self.assertIn("no usage report", text)
      status, text = run_cli("usage", self.build / "usage" / GAME / "scripts.json")
      self.assertEqual(status, ERROR_STATUS)
      self.assertIn("capsule.usage-report/1", text)


if __name__ == "__main__":
   unittest.main()
