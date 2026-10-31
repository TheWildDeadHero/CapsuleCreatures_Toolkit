#!/usr/bin/env python3
"""!Tests of core.placeholders (a scripts manifest's field placeholders and
terms, engine E9) and the `script placeholder|term ...` commands, on a
small scripts manifest written per test.
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import placeholders  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.scripts import ScriptProject  # noqa: E402

## The test source: a variable and a message using a placeholder and a term.
SOURCE = """var coins : u16 permanent;
script hello {
    msgbox "Hi {player}, {@rival} waits. {player}!";
    close_msg;
}
"""
## The test manifest.
MANIFEST = {"schema": "capsule.scripts/1", "sources": ["main.cscript"], "placeholders": {"player": {"name": 7}},
            "terms": {"rival": "Rowan"}}


class PlaceholderTests(unittest.TestCase):
   """!Placeholders, terms, the history."""

   def setUp(self) -> None:
      """!Writes the manifest and opens it.
      @return None
      """
      self.dir = Path(tempfile.mkdtemp(prefix="capsule_placeholders_"))
      (self.dir / "main.cscript").write_text(SOURCE, encoding="utf-8")
      (self.dir / "scripts.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
      self.project = ScriptProject.open(self.dir / "scripts.json")

   def tearDown(self) -> None:
      """!Removes the folder.
      @return None
      """
      shutil.rmtree(self.dir, ignore_errors=True)

   def test_rows_and_edits(self) -> None:
      """!Rows with the compiler's widths and the uses; edits checked; rename follows the texts; undo / redo.
      @return None
      """
      p = self.project
      rows = placeholders.rows(p)
      self.assertEqual([(r["name"], r["kind"], r["value"], r["cells"], r["uses"]) for r in rows],
                       [("player", "name", 7, 7, 1)])
      self.assertEqual(placeholders.term_rows(p)[0]["uses"], 1)
      with placeholders.edit(p, "Add"):
         placeholders.add_placeholder(p, "money", "var", "coins")
         placeholders.add_placeholder(p, "foe", "term", "rival", {"form": "one"})
      self.assertEqual(list(p.manifest["placeholders"]), ["player", "money", "foe"])
      self.assertTrue(p.check().ok)
      with self.assertRaises(DocumentError):
         with placeholders.edit(p, "Bad"):
            placeholders.add_placeholder(p, "prompt", "name", 3)   # a control name
      with self.assertRaises(DocumentError):
         placeholders.add_placeholder(p, "x", "record", "nickname", {"form": "many"})   # record takes a slot
      with placeholders.edit(p, "Rename"):
         self.assertEqual(placeholders.rename_placeholder(p, "player", "hero"), 1)
      self.assertIn('"Hi {hero}, {@rival} waits. {hero}!"', p.texts["main.cscript"])
      self.assertEqual(list(p.manifest["placeholders"])[0], "hero")
      with self.assertRaisesRegex(DocumentError, "still used"):
         placeholders.remove_placeholder(p, "hero")
      with self.assertRaisesRegex(DocumentError, "still used"):
         placeholders.remove_term(p, "rival")
      with placeholders.edit(p, "Move"):
         placeholders.move_placeholder(p, "foe", -1)
      self.assertEqual(list(p.manifest["placeholders"]), ["hero", "foe", "money"])
      self.assertEqual(placeholders.undo_label(p), "Move")
      self.assertTrue(placeholders.undo(p))
      self.assertTrue(placeholders.undo(p))
      self.assertIn("{player}", p.texts["main.cscript"])
      self.assertTrue(placeholders.redo(p))
      self.assertIn("{hero}", p.texts["main.cscript"])
      with placeholders.edit(p, "Term"):
         placeholders.set_term(p, "creature", "Creature", "Creatures")
      self.assertEqual(p.manifest["terms"]["creature"], {"one": "Creature", "many": "Creatures"})
      with self.assertRaises(DocumentError):
         placeholders.set_markup(p, False)   # placeholders are declared
      self.assertTrue(any(line.startswith("{hero}") for line in placeholders.lines(p)))

   def test_commands(self) -> None:
      """!`script placeholder|term ...` save when the scripts compile.
      @return None
      """
      m = self.dir / "scripts.json"

      def run(*argv: object) -> int:
         """!Runs a command quietly.
         @param argv  arguments
         @return status
         """
         with redirect_stdout(io.StringIO()):
            return cli(["script"] + [str(a) for a in argv])

      self.assertEqual(run("placeholder", m, "add", "money", "var", "coins"), 0)
      self.assertEqual(run("placeholder", m, "add", "gold", "var", "nothing"), 1)   # no such variable
      self.assertEqual(run("placeholder", m, "rename", "player", "hero"), 0)
      self.assertEqual(run("term", m, "set", "rival", "Mira", "--plural", "Miras"), 0)
      saved = json.loads(m.read_text(encoding="utf-8"))
      self.assertEqual(list(saved["placeholders"]), ["hero", "money"])
      self.assertEqual(saved["terms"]["rival"], {"one": "Mira", "many": "Miras"})
      self.assertIn("{hero}", (self.dir / "main.cscript").read_text(encoding="utf-8"))
      self.assertEqual(run("placeholders", m), 0)


if __name__ == "__main__":
   unittest.main()
