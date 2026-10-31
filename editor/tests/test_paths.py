#!/usr/bin/env python3
"""!Paths the same on Linux, Windows and macOS (D-40 RX2): core.paths and the checks that use it.

  - is_absolute_text(): POSIX, Windows drive and UNC paths are absolute on every system; relative ones are not.
    pathlib alone answers for the running system only (on Windows "/x" is relative, on Linux "C:/x" is).
  - relative(), inside(), shown(): both sides resolved, so a folder reached through a link (macOS /var is a link to
    /private/var; Windows short names such as RUNNER~1 resolve the same way) gives the short relative path, not
    one that climbs to the root and back; "/" between parts; another drive (Windows) is a clear DocumentError, or
    the absolute path for a label.
  - The manifest checks that refuse absolute paths (text box images, battle data files, sample copies) refuse
    Windows ones too.
"""
from __future__ import annotations

import ntpath
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path, PureWindowsPath
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capsule_studio.core import manifest_io, paths, samples, text_boxes  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402

## Path texts absolute on some system the toolkit runs on.
ABSOLUTE = ("/abs/frame.png", "\\abs\\frame.png", "C:/art/frame.png", "C:\\art\\frame.png", "d:frame.png",
            "\\\\server\\share\\frame.png", "//server/share/frame.png")
## Path texts relative everywhere.
RELATIVE = ("frame.png", "art/frame.png", "art\\frame.png", "../shared/frame.png", "./frame.png", "ab:c.png")
## How deep the real folder is below the link's folder (deeper than the link, as /private/var is below /var).
REAL_DEPTH = ("real", "one", "two")


class AbsoluteTextTests(unittest.TestCase):
   """!is_absolute_text() against the systems' own rules."""

   def test_absolute_on_any_system(self) -> None:
      """!Every text Windows or POSIX calls absolute (or drive-relative) counts; relative ones do not.
      @return None
      """
      for text in ABSOLUTE:
         with self.subTest(text=text):
            self.assertTrue(paths.is_absolute_text(text))
      for text in RELATIVE:
         with self.subTest(text=text):
            self.assertFalse(paths.is_absolute_text(text))

   def test_agrees_with_windows_rules(self) -> None:
      """!A text Windows gives a drive or a root (ntpath, PureWindowsPath) is absolute here on every system.
      @return None
      """
      for text in ABSOLUTE + RELATIVE:
         with self.subTest(text=text):
            windows_anchored = bool(PureWindowsPath(text).anchor) or ntpath.isabs(text)
            if windows_anchored:
               self.assertTrue(paths.is_absolute_text(text))


class RelativeTests(unittest.TestCase):
   """!relative(), inside() and shown() through a linked folder, and across drives."""

   def setUp(self) -> None:
      """!A real folder and a link to it at a shallower depth (as macOS's /var links to /private/var).
      @return None
      """
      ## The temporary folder (resolved: it is the real place both spellings lead to).
      self.root = Path(tempfile.mkdtemp(prefix="capsule_paths_")).resolve()
      ## The real game folder.
      self.real = self.root.joinpath(*REAL_DEPTH)
      (self.real / "data").mkdir(parents=True)
      manifest_io.save(self.real / "data" / "assets.json", {"schema": "capsule.assets/1", "id": "t", "assets": []})
      ## The same folder through a link (None where links cannot be made).
      self.link: Path | None = self.root / "link"
      try:
         os.symlink(self.real, self.link, target_is_directory=True)
      except (OSError, NotImplementedError):   # Windows without the right to make links
         self.link = None

   def tearDown(self) -> None:
      """!Removes the temporary folder.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def test_plain_folder(self) -> None:
      """!Inside, outside and the folder itself, written with "/".
      @return None
      """
      target = self.real / "data" / "assets.json"
      self.assertEqual(paths.relative(target, self.real), "data/assets.json")
      self.assertEqual(paths.relative(self.root / "x.json", self.real / "data"), "../../../../x.json")
      self.assertEqual(paths.inside(target, self.real), "data/assets.json")
      self.assertEqual(paths.inside(self.real, self.real), ".")
      self.assertIsNone(paths.inside(self.root, self.real))
      self.assertEqual(paths.shown(target, self.real), "data/assets.json")
      self.assertEqual(paths.shown(self.root, self.real), self.root.as_posix())

   def test_linked_folder(self) -> None:
      """!A resolved file against its folder spelled through the link, and the other way round: the short path.
      @return None
      """
      if self.link is None:
         self.skipTest("links cannot be made here")
      real_file = (self.real / "data" / "assets.json").resolve()
      linked_file = self.link / "data" / "assets.json"
      self.assertEqual(paths.relative(real_file, self.link), "data/assets.json")
      self.assertEqual(paths.relative(linked_file, self.real), "data/assets.json")
      self.assertEqual(paths.relative(real_file, self.link / "data", label=True), "assets.json")
      self.assertEqual(paths.inside(real_file, self.link), "data/assets.json")
      self.assertEqual(paths.shown(linked_file, self.real), "data/assets.json")
      # What os.path.relpath alone gives here: a path that climbs out of the link and back down.
      self.assertNotEqual(Path(os.path.relpath(real_file, self.link)).as_posix(), "data/assets.json")

   def test_another_drive(self) -> None:
      """!No relative path between drives (Windows): an error that says so, or the absolute path for a label.
      @return None
      """
      target = self.real / "data" / "assets.json"
      with mock.patch.object(paths.os.path, "relpath", side_effect=ValueError("path is on mount 'D:'")):
         with self.assertRaises(DocumentError) as raised:
            paths.relative(target, self.root)
         self.assertIn("another drive", str(raised.exception))
         self.assertEqual(paths.relative(target, self.root, label=True), target.resolve().as_posix())

   def test_windows_relpath_raises(self) -> None:
      """!The Windows rule relative() handles: ntpath.relpath refuses two drives.
      @return None
      """
      with self.assertRaises(ValueError):
         ntpath.relpath("D:\\a\\engine\\samples\\starter", "C:\\Users\\runner\\Temp\\demo")
      self.assertEqual(ntpath.relpath("C:\\t\\g\\data\\a.json", "C:\\t\\g").replace(ntpath.sep, "/"),
                       "data/a.json")


class AbsoluteRefusalTests(unittest.TestCase):
   """!Manifest checks refuse absolute paths of every system."""

   def test_text_box_images(self) -> None:
      """!A text box image path: Windows and POSIX absolute paths refused; relative ones kept with "/".
      @return None
      """
      for text in ABSOLUTE:
         with self.subTest(text=text):
            with self.assertRaises(DocumentError):
               text_boxes._relative_path(text)
      self.assertEqual(text_boxes._relative_path("art\\frame.png"), "art/frame.png")

   def test_sample_outside_paths(self) -> None:
      """!An absolute path that exists, written as the running system writes it, ties a game to the outside.
      @return None
      """
      root = Path(tempfile.mkdtemp(prefix="capsule_paths_game_")).resolve()
      self.addCleanup(shutil.rmtree, root, True)
      outside = root / "outside.png"
      outside.write_bytes(b"")
      game = root / "game"
      manifest_io.save(game / "reference" / "project.json",
                       {"schema": "capsule.project/1", "name": "g", "image": str(outside)})
      problems = samples.outside_paths(game)
      self.assertEqual(len(problems), 1, problems)
      self.assertIn("outside.png", problems[0])


if __name__ == "__main__":
   unittest.main()
