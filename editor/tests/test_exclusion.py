"""!D-36 package 3 step 3C: core/exclusion.py and `capsule-studio exclude` (cli/exclude_cmds.py) on a sample build
folder (a report merged by the engine's tools/usage.py, the build's suggestion from tools/usage_exclude.py, a check's
findings, a GBA symbol listing) and a sample project: the tables' rows, the manifest built from choices with its
reasons, saving it (creating it and naming it in the project, or into the file the project names), a refused
manifest, and the command's summary and --write. Skipped with an engine before the exclusion manifest."""
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
from capsule_studio.core import engine, exclusion, project  # noqa: E402

## The game.
GAME = "demo"
## The scripts' opcodes.
SCRIPT_OPS = {"End": 2, "Message": 1}
## A GBA symbol listing: one script symbol and one sequence symbol (bytes 0x30 and 0x10).
NM = "08000000 00000030 T _ZN7capsule6script3runEv\n08000030 00000010 t _ZN7capsule3seq4tickEv\n"
## The sequence symbol's bytes.
SEQ_BYTES = 0x10
## A check's output.
FINDINGS = ("error: module seq is excluded but used: seq.op (the usage report)\n"
            "note: script op Shop: no script emits it; it could be excluded\n"
            "exclude_check: 1 errors, 0 warnings, 1 suggestions\n")
## Exit status of a command error.
ERROR_STATUS = 1


def have_tools() -> str | None:
   """!Why the tests cannot run, or None.
   @return the reason
   """
   try:
      exclusion.tools()
   except exclusion.ExclusionError as e:
      return str(e)
   return None


@unittest.skipIf(have_tools() is not None, f"{have_tools()}")
class ExclusionTests(unittest.TestCase):
   """!The core and the command on one sample build folder and project."""

   def setUp(self) -> None:
      """!The build folder (report, suggestion, findings, listing) and a project naming no manifest."""
      self.usage_tool, self.exclude_tool = exclusion.tools()
      self.tmp = tempfile.TemporaryDirectory()
      root = Path(self.tmp.name).resolve()
      self.build = root / "build-gba"
      record = self.build / "usage" / GAME / "scripts.json"
      self.usage_tool.write_record(record, GAME, "script", {"script.op": SCRIPT_OPS})
      report = self.build / "usage" / f"{GAME}.json"
      self.assertEqual(self.usage_tool.main(["merge", str(record), "--game", GAME, "--out", str(report)]), 0)
      self.report = self.usage_tool.read_report(report)
      self.suggestion = self.exclude_tool.generate(self.report, {}, self.exclude_tool.script_ops(), "usage/demo.json")
      (self.build / "usage" / f"{GAME}.exclude.json").write_text(self.exclude_tool.manifest_text(self.suggestion),
                                                                 encoding="utf-8")
      (self.build / "usage" / f"{GAME}.exclude-check.txt").write_text(FINDINGS, encoding="utf-8")
      (self.build / f"capsule_{GAME}.nm").write_text(NM, encoding="utf-8")
      self.project_file = root / "game" / "reference" / "project.json"
      self.project_file.parent.mkdir(parents=True)
      self.project_file.write_text(json.dumps({"schema": project.SCHEMA, "name": GAME}), encoding="utf-8")

   def tearDown(self) -> None:
      """!Removes the folders."""
      self.tmp.cleanup()

   def test_rows(self) -> None:
      """!The modules (used, suggested, bytes) and the ops (emitted, suggested), with and without a manifest."""
      usage = exclusion.read_build(self.build, GAME)
      self.assertEqual(usage.findings, [("error", "module seq is excluded but used: seq.op (the usage report)"),
                                        ("note", "script op Shop: no script emits it; it could be excluded")])
      self.assertEqual(usage.nm_path.name, f"capsule_{GAME}.nm")
      rows = {r.name: r for r in exclusion.module_rows(usage, None)}
      self.assertTrue(rows["script"].used_by)
      self.assertFalse(rows["script"].excludable)
      self.assertTrue(rows["seq"].excludable and rows["seq"].suggested and not rows["seq"].excluded)
      self.assertEqual(rows["seq"].gba_bytes, SEQ_BYTES)
      self.assertFalse(rows["seq"].game_code)
      ops = {o.name: o for o in exclusion.op_rows(usage, None)}
      self.assertEqual(ops["Message"].emitted, SCRIPT_OPS["Message"])
      self.assertFalse(ops["Message"].suggested)
      self.assertTrue(ops["Shop"].suggested)
      # a module the build did not offer while nothing records it: the game's code calls it
      usage.suggestion = dict(self.suggestion, modules=[m for m in self.suggestion["modules"] if m["name"] != "seq"])
      self.assertTrue({r.name: r for r in exclusion.module_rows(usage, None)}["seq"].game_code)

   def test_save(self) -> None:
      """!The manifest of choices keeps the build's reasons; Save creates reference/exclude.json and names it, then
      writes the file the project names; a manifest that does not validate is refused."""
      usage = exclusion.read_build(self.build, GAME)
      doc = project.open_project(self.project_file)
      manifest = exclusion.build_manifest(usage, ["seq", "seq"], ["Shop", "Message"])
      self.assertEqual(exclusion.names(manifest, exclusion.MODULES), ["seq"])
      reasons = {i["name"]: i["reason"] for i in manifest[exclusion.SCRIPT_OPS]}
      self.assertEqual(reasons["Message"], exclusion.STUDIO_REASON)
      self.assertEqual(reasons["Shop"], self.exclude_tool.OP_REASON)
      path, added = exclusion.save(doc, manifest)
      self.assertTrue(added)
      self.assertEqual(doc.data[exclusion.EXCLUDE_KEY], exclusion.DEFAULT_MANIFEST)
      self.assertEqual(path, (self.project_file.parent.parent / exclusion.DEFAULT_MANIFEST).resolve())
      self.assertEqual(exclusion.read_manifest(doc), manifest)
      rows = {r.name: r for r in exclusion.module_rows(usage, exclusion.read_manifest(doc))}
      self.assertTrue(rows["seq"].excluded)
      again = exclusion.build_manifest(usage, [], ["Message"], manifest)
      self.assertEqual(exclusion.save(doc, again), (path, False))
      with self.assertRaises(exclusion.ExclusionError):
         exclusion.save(doc, {"schema": "nope"})

   def test_command(self) -> None:
      """!The summary; --write saves the suggestion and names it in the project; a folder without the report."""
      status, out = self.run_cli("exclude", self.project_file, "--build", self.build)
      self.assertEqual(status, 0)
      self.assertIn("seq: can be excluded, 16 B on the GBA", out)
      self.assertIn("error: module seq is excluded", out)
      status, out = self.run_cli("exclude", self.project_file, "--build", self.build, "--write")
      self.assertEqual(status, 0)
      self.assertIn("the project now names it", out)
      self.assertIn("seq: excluded", out)
      saved = json.loads(self.project_file.read_text(encoding="utf-8"))
      self.assertEqual(saved[exclusion.EXCLUDE_KEY], exclusion.DEFAULT_MANIFEST)
      status, out = self.run_cli("exclude", self.project_file, "--build", self.build / "nothing")
      self.assertEqual(status, ERROR_STATUS)
      self.assertIn("no usage report", out)

   def run_cli(self, *argv: object) -> tuple[int, str]:
      """!Runs the capsule-studio command line.
      @param argv  arguments
      @return (status, stdout + stderr)
      """
      out, err = io.StringIO(), io.StringIO()
      with redirect_stdout(out), redirect_stderr(err):
         status = cli([str(a) for a in argv])
      return status, out.getvalue() + err.getvalue()


if __name__ == "__main__":
   unittest.main()
