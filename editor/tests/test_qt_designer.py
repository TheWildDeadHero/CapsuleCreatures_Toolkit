#!/usr/bin/env python3
"""!Smoke test of the manifest designer's window (ui/designer) on a Sample flow manifest, driven with real mouse and
key events: dragging (grid snapping, a frame carrying its contents), drawing wires (ports that do not fit fade),
dropping a wire in empty space, connectors, resizing, rubber-band selection, nudging, deleting, undo; the palette,
add-by-typing, the inspector, copy and paste, problems, saving with the view, and scroll bars that are never
locked. Skipped when PySide6 is missing; uses Qt's offscreen platform.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
   from PySide6 import QtCore, QtGui, QtWidgets
   from PySide6.QtTest import QTest
except ImportError:   # the headless toolkit (core only)
   QtWidgets = None

from capsule_studio.core.designer.model import Endpoint  # noqa: E402
from capsule_studio.core.designer.session import DesignSession  # noqa: E402

E = Endpoint.parse


def build_flow(path: Path) -> None:
   """!Writes a flow: 5 x 6 compared with 20, chosen into a Show inside a frame, with a note.
   @param path  where
   @return None
   """
   s = DesignSession.new("sample-flow", path)
   s.add("number", (0, 0), {"value": 5})
   s.add("number", (0, 120), {"value": 6})
   s.add("multiply", (240, 40))
   s.add("number", (240, 200), {"value": 20})
   s.add("compare", (480, 80), {"test": ">"})
   s.add("choose", (720, 40))
   s.add("show", (960, 60), {"label": "Bigger"})
   for a, b in (("n1.value", "n3.a"), ("n2.value", "n3.b"), ("n3.result", "n5.a"), ("n4.value", "n5.b"),
                ("n5.result", "n6.when"), ("n3.result", "n6.yes"), ("n4.value", "n6.no"), ("n6.result", "n7.value")):
      s.connect(E(a), E(b))
   s.add("frame", (920, 20))
   s.add("note", (0, 320), {"text": "Numbers flow left to right"})
   s.save()


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class QtDesignerTests(unittest.TestCase):
   """!The window on a copy of the flow."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

   def setUp(self) -> None:
      """!Writes the flow and opens it.
      @return None
      """
      from capsule_studio.ui.designer.window import DesignerWindow
      ## Temporary folder.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_qt_designer_"))
      QtCore.QSettings.setPath(QtCore.QSettings.Format.NativeFormat, QtCore.QSettings.Scope.UserScope,
                               str(self.root / "settings"))
      ## The manifest.
      self.path = self.root / "flow.json"
      build_flow(self.path)
      ## The window.
      self.w = DesignerWindow(self.path)
      self.w.resize(1400, 860)
      self.w.show()
      self.settle()
      self.w.view.set_zoom(100)
      self.w.view.centerOn(QtCore.QPointF(500, 200))
      self.settle()

   def tearDown(self) -> None:
      """!Closes without asking and removes the folder.
      @return None
      """
      self.w.session.doc.dirty = False
      self.w.close()
      # Qt's offscreen platform crashes at exit while the clipboard still holds data a test put there.
      QtWidgets.QApplication.clipboard().clear()
      self.settle()
      shutil.rmtree(self.root, ignore_errors=True)

   def settle(self) -> None:
      """!Runs pending events (scheduled refreshes).
      @return None
      """
      for _ in range(5):
         self.app.processEvents()

   # -- mouse on the canvas -------------------------------------------------------------------------------------------

   def at(self, p: QtCore.QPointF) -> QtCore.QPoint:
      """!A canvas point in the viewport.
      @param p  canvas point
      @return viewport point
      """
      return self.w.view.mapFromScene(p)

   def press(self, p: QtCore.QPointF) -> None:
      """!Left button down.
      @param p  canvas point
      @return None
      """
      QTest.mousePress(self.w.view.viewport(), QtCore.Qt.MouseButton.LeftButton,
                       QtCore.Qt.KeyboardModifier.NoModifier, self.at(p))

   def move(self, p: QtCore.QPointF) -> None:
      """!Mouse moved with the left button down.
      @param p  canvas point
      @return None
      """
      vp = self.w.view.viewport()
      left = QtCore.Qt.MouseButton.LeftButton
      event = QtGui.QMouseEvent(QtCore.QEvent.Type.MouseMove, QtCore.QPointF(self.at(p)),
                                QtCore.QPointF(vp.mapToGlobal(self.at(p))), left, left,
                                QtCore.Qt.KeyboardModifier.NoModifier)
      self.app.sendEvent(vp, event)

   def release(self, p: QtCore.QPointF) -> None:
      """!Left button up.
      @param p  canvas point
      @return None
      """
      QTest.mouseRelease(self.w.view.viewport(), QtCore.Qt.MouseButton.LeftButton,
                         QtCore.Qt.KeyboardModifier.NoModifier, self.at(p))
      self.settle()

   def drag(self, a: QtCore.QPointF, b: QtCore.QPointF) -> None:
      """!A drag from one point to another (in two steps).
      @param a  start
      @param b  end
      @return None
      """
      self.press(a)
      self.move((a + b) / 2)
      self.move(b)
      self.release(b)

   def diagram(self) -> object:
      """!The session's diagram.
      @return the diagram
      """
      return self.w.session.diagram()

   # -- tests -------------------------------------------------------------------------------------------------------

   def test_window_shows_the_flow(self) -> None:
      """!Title, palette, live values, problems, and scroll bars that are never switched off.
      @return None
      """
      w, sc = self.w, self.w.scene
      self.assertEqual(w.windowTitle(), "flow.json - Manifest Designer (Sample flow)")
      self.assertEqual(len(sc.element_items), len(self.diagram().elements))
      self.assertEqual(sc.element_items["n6"].value, "30")
      self.assertEqual(w.problems.item(0).text(), "No problems")
      self.assertEqual(w.palette.kind_ids()[:2], ["number", "add"])
      w.palette.search.setText("note")
      self.assertEqual(w.palette.kind_ids(), ["note"])
      mime = w.palette.tree.mimeData([w.palette.tree.topLevelItem(0).child(0)])
      self.assertEqual(bytes(mime.data("application/x-capsule-designer-kind").data()), b"note")
      never = QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
      self.assertNotEqual(w.view.horizontalScrollBarPolicy(), never)
      self.assertNotEqual(w.view.verticalScrollBarPolicy(), never)
      self.assertTrue(w.view.horizontalScrollBar().isVisible())

   def test_drags(self) -> None:
      """!Moving snaps to the grid as one undo step; a frame carries what it holds; a shape resizes by its corner.
      @return None
      """
      sc = self.w.scene
      start = sc.element_items["n4"].pos() + QtCore.QPointF(60, 10)
      self.drag(start, start + QtCore.QPointF(37, 13))
      self.assertEqual(self.diagram().elements["n4"].pos, (280, 220))
      self.assertEqual(self.w.session.doc.undo_label(), "Move n4")
      self.assertTrue(self.w.windowTitle().startswith("flow.json * - "))
      self.assertEqual(self.diagram().elements["n7"].parent, "frame1")
      title = sc.element_items["frame1"].pos() + QtCore.QPointF(60, 8)
      # (Its middle lines up with the note's top on the way: the guide holds it exactly there.)
      self.drag(title, title + QtCore.QPointF(20, 160))
      self.assertEqual(self.diagram().elements["frame1"].pos, (940, 180))
      self.assertEqual(self.diagram().elements["n7"].pos, (980, 220))
      sc.select_ids(["note1"])
      self.settle()
      corner = sc.element_items["note1"].resizer.scenePos() + QtCore.QPointF(4, 4)
      self.drag(corner, corner + QtCore.QPointF(43, 21))
      self.assertEqual(self.diagram().elements["note1"].size, (200, 100))

   def test_alignment_guides(self) -> None:
      """!With the grid off, an edge dragged near another's lines up with it and a guide shows while dragging.
      @return None
      """
      sc = self.w.scene
      sc.snap_to_grid = False
      grab = sc.element_items["n2"].pos() + QtCore.QPointF(60, 10)
      self.press(grab)
      self.move(grab + QtCore.QPointF(0, 40))
      self.move(grab + QtCore.QPointF(0, 83))   # its top to 203, near Number 20's top (200)
      self.assertTrue(sc.guides)
      self.release(grab + QtCore.QPointF(0, 83))
      self.assertEqual(self.diagram().elements["n2"].pos, (0, 200))
      self.assertFalse(sc.guides)

   def test_wires_and_connectors(self) -> None:
      """!A wire drawn port to port (ports that do not fit fade meanwhile); a wire dropped in empty space asks for
      a node and adds it wired; a connector from the note's handle.
      @return None
      """
      sc = self.w.scene
      link = next(k for k in self.diagram().links.values() if k.target.text() == "n6.no")
      self.w.session.disconnect([link.link_id])
      self.settle()
      src = sc.element_items["n4"].ports["value"].scenePos()
      dst = sc.element_items["n6"].ports["no"].scenePos()
      self.press(src)
      self.move((src + dst) / 2)
      faded = {p.spec.name for p in sc.element_items["n6"].ports.values() if p.opacity() < 1}
      self.assertEqual(faded, {"when", "yes", "result"})   # "no" fits; "yes" takes one wire, "when" is yes/no
      self.move(dst)
      self.release(dst)
      self.assertTrue(any(k.target.text() == "n6.no" for k in self.diagram().links.values()))
      asked = []
      sc.add_requested.connect(lambda screen, pos, wire_from: asked.append((pos, wire_from)))
      src = sc.element_items["n3"].ports["result"].scenePos()
      self.drag(src, QtCore.QPointF(300, 520))
      self.assertEqual(asked[-1][1], "n3.result")
      quick = self.w.quick_add
      self.assertIsNotNone(quick)
      self.assertNotIn("Number", [quick.list.item(n).text().split()[0] for n in range(quick.list.count())])
      quick.edit.setText("show")
      quick.pick()
      self.settle()
      new = sc.selected_elements()[0]
      self.assertTrue(any(k.source.text() == "n3.result" and k.target.element == new
                          for k in self.diagram().links.values()))
      note = sc.element_items["note1"]
      sc.select_ids(["note1"])
      self.settle()
      self.drag(note.connector.scenePos(), sc.element_items["n5"].box().center())
      self.assertTrue(any(k.annotation and k.target.element == "n5" for k in self.diagram().links.values()))

   def test_selection_and_keys(self) -> None:
      """!Rubber band, nudge, Delete and Undo.
      @return None
      """
      sc = self.w.scene
      self.drag(QtCore.QPointF(-30, -30), QtCore.QPointF(200, 180))
      self.assertEqual(sorted(sc.selected_elements()), ["n1", "n2"])
      self.w.view.setFocus()
      QTest.keyClick(self.w.view.viewport(), QtCore.Qt.Key.Key_Right)
      self.settle()
      self.assertEqual(self.diagram().elements["n1"].pos, (20, 0))
      QTest.keyClick(self.w.view.viewport(), QtCore.Qt.Key.Key_Delete)
      self.settle()
      self.assertNotIn("n1", self.diagram().elements)
      self.assertIn("n3: a needs a wire", [self.w.problems.item(n).text().split(": ", 1)[1]
                                           for n in range(self.w.problems.count())])
      self.w.undo()
      self.settle()
      self.assertIn("n1", self.diagram().elements)

   def test_inspector_and_clipboard(self) -> None:
      """!The inspector sets fields and positions; copy and paste carry the wires between the copies; Tidy up and
      Save keep the view.
      @return None
      """
      sc = self.w.scene
      sc.select_ids(["n1"])
      self.settle()
      editors = self.w.inspector.editors
      editors["value"].setValue(9)
      editors["value"].editingFinished.emit()
      self.settle()
      self.assertEqual(self.diagram().elements["n1"].properties["value"], 9)
      self.assertEqual(sc.element_items["n3"].value, "54")
      self.w.inspector.editors["x"].setValue(40)
      self.w.inspector.editors["x"].editingFinished.emit()
      self.settle()
      self.assertEqual(self.diagram().elements["n1"].pos, (40, 0))
      sc.select_ids(["n5"])
      self.settle()
      self.w.inspector.editors["test"].setCurrentText("<")
      self.w.inspector.editors["test"].activated.emit(0)
      self.settle()
      self.assertEqual(self.diagram().elements["n5"].properties["test"], "<")
      sc.select_ids(["n1", "n2", "n3"])
      self.assertTrue(self.w.copy())
      count = len(self.diagram().links)
      self.w.paste()
      self.settle()
      self.assertEqual(len(sc.selected_elements()), 3)
      self.assertEqual(len(self.diagram().links), count + 2)
      self.w.tidy_up()
      self.settle()
      self.assertEqual(self.w.session.doc.undo_label(), "Tidy up")
      self.w.view.set_zoom(150)
      self.assertTrue(self.w.save_file())
      saved = json.loads(self.path.read_text())
      self.assertEqual(saved["editor"]["designer"]["view"]["zoom"], 150)
      self.assertEqual(self.w.windowTitle(), "flow.json - Manifest Designer (Sample flow)")

   def test_start_page_and_new(self) -> None:
      """!With nothing open, the start page shows; New starts a manifest of the chosen system.
      @return None
      """
      from capsule_studio.ui.designer.window import DesignerWindow
      empty = DesignerWindow()
      empty.launch()
      self.settle()
      self.assertTrue(empty.start.isVisible())
      self.assertTrue(empty.new_file("sample-flow"))
      self.settle()
      self.assertFalse(empty.start.isVisible())
      self.assertEqual(empty.windowTitle(), "untitled - Manifest Designer (Sample flow)")
      element = empty.add_in_view("number")
      self.assertIsNotNone(element)
      empty.session.doc.dirty = False
      self.assertTrue(empty.open_file(self.path))   # a second manifest replaces the canvas and panels
      self.settle()
      self.assertEqual(len(empty.scene.element_items), len(self.diagram().elements))
      self.assertEqual(empty.windowTitle(), "flow.json - Manifest Designer (Sample flow)")
      empty.close()


if __name__ == "__main__":
   unittest.main()
