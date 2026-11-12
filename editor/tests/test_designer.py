#!/usr/bin/env python3
"""!Tests of the manifest designer's core (core.designer, no Qt) and `capsule-studio designer`: the model, the
shared edits and checks, auto-layout, the session's undo steps and editor block, the Sample flow system and the
command line.
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capsule_studio.cli.main import main  # noqa: E402
from capsule_studio.core.designer import checks, layout, ops, registry  # noqa: E402
from capsule_studio.core.designer.model import (Diagram, Element, Endpoint, Link, ModelError,  # noqa: E402
                                                PropertySpec)
from capsule_studio.core.designer.sample_flow import SCHEMA  # noqa: E402
from capsule_studio.core.designer.session import DesignSession  # noqa: E402
from capsule_studio.core.designer.system import DesignerSystem  # noqa: E402

E = Endpoint.parse


def flow(session: DesignSession) -> None:
   """!Builds 5 x 6 -> Show, with a note pointing at the Multiply.
   @param session  a Sample flow session
   @return None
   """
   session.add("number", (0, 0), {"value": 5})
   session.add("number", (0, 120), {"value": 6})
   session.add("multiply", (240, 40))
   session.add("show", (480, 40), {"label": "Product"})
   session.connect(E("n1.value"), E("n3.a"))
   session.connect(E("n2.value"), E("n3.b"))
   session.connect(E("n3.result"), E("n4.value"))
   session.add("note", (0, 300), {"text": "Why"})
   session.connect(E("note1"), E("n3"), "multiplies")


class ModelTests(unittest.TestCase):
   """!Values, endpoints and the JSON form."""

   def test_fields_convert_text(self) -> None:
      """!Each field type takes its value (or text for it), and refuses what does not fit.
      @return None
      """
      self.assertEqual(PropertySpec("v", "V", "integer", minimum=0, maximum=9).coerce("7"), 7)
      with self.assertRaises(ModelError):
         PropertySpec("v", "V", "integer", minimum=0, maximum=9).coerce(10)
      with self.assertRaises(ModelError):
         PropertySpec("v", "V", "integer").coerce(True)
      self.assertIs(PropertySpec("b", "B", "boolean").coerce("yes"), True)
      self.assertEqual(PropertySpec("c", "C", "choice", choices=("<", ">")).coerce(">"), ">")
      with self.assertRaises(ModelError):
         PropertySpec("c", "C", "choice", choices=("<", ">")).coerce("=")
      self.assertEqual(PropertySpec("f", "F", "colour").coerce("#AABBCC"), "#aabbcc")
      with self.assertRaises(ModelError):
         PropertySpec("f", "F", "colour").coerce("red")

   def test_endpoints_and_json(self) -> None:
      """!"element.port" splits at the last dot; a diagram round-trips through JSON.
      @return None
      """
      self.assertEqual(E("n1.value"), Endpoint("n1", "value"))
      self.assertEqual(E("note1"), Endpoint("note1"))
      d = Diagram({"a": Element("a", "number", (1, 2), (0, 0), {"value": 3})},
                  {"w1": Link("w1", E("a.value"), E("b.a"), "x")}, {"zoom": 100})
      self.assertEqual(Diagram.from_json(json.loads(json.dumps(d.to_json()))).to_json(), d.to_json())

   def test_frames_that_hold_each_other_do_not_loop(self) -> None:
      """!A malformed manifest with two frames holding each other still answers descendants().
      @return None
      """
      d = Diagram({"f1": Element("f1", "frame", parent="f2"), "f2": Element("f2", "frame", parent="f1")})
      self.assertEqual([e.element_id for e in d.descendants("f1")], ["f2"])


class SessionTests(unittest.TestCase):
   """!A Sample flow manifest in a temporary folder."""

   def setUp(self) -> None:
      """!A new session.
      @return None
      """
      ## Temporary folder.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_designer_"))
      ## The manifest's path.
      self.path = self.root / "flow.json"
      ## The session.
      self.s = DesignSession.new("sample-flow", self.path)

   def tearDown(self) -> None:
      """!Removes the folder.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def test_flow_values_and_manifest(self) -> None:
      """!Nodes and wires go into the manifest inline; notes and connectors into the editor block; values flow.
      @return None
      """
      flow(self.s)
      self.assertEqual(self.s.live_values(), {"n1": "5", "n2": "6", "n3": "30", "n4": "30"})
      self.assertEqual(self.s.diagnostics(), [])
      self.s.save(view={"zoom": 100, "centre": [10, 20]})
      data = json.loads(self.path.read_text())
      self.assertEqual(data["schema"], SCHEMA)
      self.assertEqual(data["nodes"]["n4"], {"kind": "show", "pos": [480, 40], "label": "Product"})
      self.assertEqual(data["wires"][0], {"from": "n1.value", "to": "n3.a"})
      block = data["editor"]["designer"]
      self.assertEqual([s["id"] for s in block["shapes"]], ["note1"])
      self.assertEqual(block["connectors"], [{"id": "c1", "from": "note1", "to": "n3", "label": "multiplies"}])
      self.assertEqual(block["view"], {"zoom": 100, "centre": [10, 20]})
      self.assertFalse(self.s.doc.dirty)
      again = DesignSession.open(self.path)
      self.assertEqual(again.diagram().to_json(), self.s.diagram().to_json())

   def test_each_edit_is_one_undo_step(self) -> None:
      """!Edits are labelled undo steps; a refused edit changes nothing.
      @return None
      """
      flow(self.s)
      self.assertEqual(self.s.doc.undo_label(), "Connect note1 to n3")
      before = json.dumps(self.s.doc.data)
      with self.assertRaises(ModelError):
         self.s.connect(E("n1.value"), E("n3.a"))   # n3.a takes one wire
      with self.assertRaises(ModelError):
         self.s.set_properties("n1", {"value": "x"})
      self.assertEqual(json.dumps(self.s.doc.data), before)
      self.s.move(["n1", "n2"], 20, 0)
      self.assertEqual(self.s.doc.undo_label(), "Move n1, n2")
      self.assertTrue(self.s.doc.undo())
      self.assertEqual(self.s.diagram().elements["n1"].pos, (0, 0))
      self.assertTrue(self.s.doc.redo())
      self.assertEqual(self.s.diagram().elements["n1"].pos, (20, 0))

   def test_link_rules(self) -> None:
      """!Types must fit, an input takes one wire, outputs feed inputs, no loops, no wire to itself.
      @return None
      """
      flow(self.s)
      self.s.add("compare", (240, 200))
      problem = checks.link_problem(self.s.system, self.s.diagram(), E("n5.result"), E("n3.a"))
      self.assertIn("boolean does not fit number", problem)
      self.assertIn("output to an input", checks.link_problem(self.s.system, self.s.diagram(), E("n3.a"),
                                                              E("n5.a")))
      self.assertIn("itself", checks.link_problem(self.s.system, self.s.diagram(), E("n3.result"), E("n3.a")))
      self.s.add("add", (480, 200))
      self.s.connect(E("n3.result"), E("n6.a"))
      self.s.connect(E("n6.result"), E("n5.a"))
      # A loop is refused by the checks (the manifest may hold one; the canvas shows it as a problem).
      self.s.edit("loop", lambda d: d.links.update({"x": Link("x", E("n6.result"), E("n6.b"))}))
      messages = [p.message for p in self.s.diagnostics()]
      self.assertTrue(any("form a loop" in m or "itself" in m for m in messages), messages)

   def test_required_inputs_and_system_check(self) -> None:
      """!An unwired required input is an error; a flow without a Show is a warning.
      @return None
      """
      self.s.add("add", (0, 0))
      messages = [(p.severity, p.message) for p in self.s.diagnostics()]
      self.assertIn(("error", "n1: a needs a wire"), messages)
      self.assertIn(("warning", "nothing is shown: add a Show node"), messages)

   def test_frames(self) -> None:
      """!A frame dropped over a node takes it in; moving the frame carries it; a node dragged out leaves it;
      removing the frame removes what it holds.
      @return None
      """
      flow(self.s)
      self.s.add("frame", (440, 0))
      self.assertEqual(self.s.diagram().elements["n4"].parent, "frame1")
      self.s.move(["frame1"], 100, 0)
      self.assertEqual(self.s.diagram().elements["n4"].pos, (580, 40))
      self.s.move(["n4"], 0, 400)
      self.assertIsNone(self.s.diagram().elements["n4"].parent)
      self.s.move(["n4"], 0, -400)
      self.assertEqual(self.s.diagram().elements["n4"].parent, "frame1")
      data = self.s.doc.data
      self.assertEqual(data["nodes"]["n4"]["editor"], {"frame": "frame1"})
      with self.assertRaises(ModelError):
         self.s.set_frame(["frame1"], "frame1")
      self.s.remove(["frame1"])
      self.assertNotIn("n4", self.s.diagram().elements)
      self.assertNotIn("editor", self.s.doc.data["nodes"].get("n3", {}))

   def test_copies(self) -> None:
      """!Duplicate and paste copy elements and the wires between them, not the wires to the rest.
      @return None
      """
      flow(self.s)
      copies = self.s.duplicate(["n1", "n2", "n3"], (0, 400))
      self.assertEqual(copies, {"n1": "n5", "n2": "n6", "n3": "n7"})
      wires = {(k.source.text(), k.target.text()) for k in self.s.diagram().links.values()}
      self.assertIn(("n5.value", "n7.a"), wires)
      self.assertNotIn(("n7.result", "n4.value"), wires)
      clip = self.s.copy(["n3", "note1"])
      made = self.s.paste(clip, (1000, 1000))
      self.assertEqual(set(made), {"n3", "note1"})
      d = self.s.diagram()
      self.assertTrue(d.elements[made["note1"]].annotation)
      self.assertTrue(any(k.source.element == made["note1"] and k.target.element == made["n3"]
                          for k in d.links.values()))

   def test_arrange(self) -> None:
      """!Align on the first, distribute between the outer two, same size as the first, front and back.
      @return None
      """
      self.s.add("rectangle", (0, 0))
      self.s.add("rectangle", (100, 50))
      self.s.add("rectangle", (400, 90))
      self.s.align(["rectangle1", "rectangle2", "rectangle3"], ops.ALIGN_TOP)
      self.assertEqual({e.pos[1] for e in self.s.diagram().elements.values()}, {0})
      self.s.distribute(["rectangle1", "rectangle2", "rectangle3"], ops.HORIZONTAL)
      self.assertEqual(self.s.diagram().elements["rectangle2"].pos[0], 200)
      self.s.resize("rectangle1", (200, 100))
      self.s.same_size(["rectangle1", "rectangle3"], ops.SAME_BOTH)
      self.assertEqual(self.s.diagram().elements["rectangle3"].size, (200, 100))
      self.s.to_back(["rectangle3"])
      self.assertEqual(list(self.s.diagram().elements)[0], "rectangle3")
      with self.assertRaises(ModelError):
         self.s.align(["rectangle1", "rectangle2"], "diagonal")
      with self.assertRaises(ModelError):
         self.s.resize("rectangle1", (1, 1))

   def test_add_wired_and_fitting_kinds(self) -> None:
      """!A wire dropped in empty space offers only kinds it fits, and adds the node already wired.
      @return None
      """
      flow(self.s)
      self.s.add("compare", (240, 200))
      self.assertEqual(self.s.fitting_kinds(E("n5.result")), ["choose"])
      node = self.s.add_wired("choose", (480, 200), E("n5.result"))
      self.assertTrue(any(k.target == Endpoint(node.element_id, "when") for k in self.s.diagram().links.values()))
      with self.assertRaises(ModelError):
         self.s.add_wired("number", (0, 0), E("n5.result"))

   def test_tidy_up(self) -> None:
      """!Auto-layout puts each node a rank after what feeds it, on the grid; notes stay put.
      @return None
      """
      self.s.add("show", (0, 0))
      self.s.add("multiply", (13, 900))
      self.s.add("number", (500, 7), {"value": 1})
      self.s.add("number", (500, 300), {"value": 2})
      self.s.connect(E("n3.value"), E("n2.a"))
      self.s.connect(E("n4.value"), E("n2.b"))
      self.s.connect(E("n2.result"), E("n1.value"))
      self.s.add("note", (777, 777))
      self.s.auto_layout()
      d = self.s.diagram()
      xs = {i: d.elements[i].pos[0] for i in ("n1", "n2", "n3", "n4")}
      self.assertEqual(xs["n3"], xs["n4"])
      self.assertLess(xs["n3"], xs["n2"])
      self.assertLess(xs["n2"], xs["n1"])
      self.assertTrue(all(v % layout.GRID == 0 for e in d.elements.values() if not e.annotation for v in e.pos))
      self.assertEqual(d.elements["note1"].pos, (777, 777))
      self.assertEqual(layout.ranks(d, ["n1", "n2", "n3", "n4"]), {"n1": 2, "n2": 1, "n3": 0, "n4": 0})

   def test_unknown_keys_survive(self) -> None:
      """!Keys a system does not own (in a node, and elsewhere in the manifest) are kept by every edit.
      @return None
      """
      flow(self.s)
      self.s.save()
      data = json.loads(self.path.read_text())
      data["nodes"]["n1"]["comment"] = "kept"
      data["notes"] = ["kept too"]
      data["editor"]["author"] = "someone"
      self.path.write_text(json.dumps(data))
      s = DesignSession.open(self.path)
      s.move(["n1"], 20, 0)
      self.assertEqual(s.doc.data["nodes"]["n1"]["comment"], "kept")
      self.assertEqual(s.doc.data["notes"], ["kept too"])
      self.assertEqual(s.doc.data["editor"]["author"], "someone")
      s.remove(["note1"])   # its connector goes with it: the designer's block empties and goes, the rest stays
      self.assertEqual(s.doc.data["editor"], {"author": "someone"})

   def test_large_diagram(self) -> None:
      """!1,000 nodes and about 1,500 wires: an edit and its checks stay quick (D-43 §5 budget, with room for slow
      machines).
      @return None
      """
      columns, rows = 20, 50

      def build(d: Diagram) -> None:
         """!Columns of nodes, each wired to the column before.
         @param d  the diagram
         @return None
         """
         for c in range(columns):
            for r in range(rows):
               ops.add_element(self.s.system, d, "number" if c == 0 else "add", (c * 240, r * 120),
                               element_id=f"c{c}r{r}")
         for c in range(1, columns):
            port = "value" if c == 1 else "result"
            for r in range(rows):
               ops.connect(self.s.system, d, E(f"c{c - 1}r{r}.{port}"), E(f"c{c}r{r}.a"))
               ops.connect(self.s.system, d, E(f"c{c - 1}r{(r + 1) % rows}.{port}"), E(f"c{c}r{r}.b"))

      self.s.edit("build", build)
      started = time.perf_counter()
      self.s.move(["c5r5"], 20, 0)
      self.assertEqual(checks.errors(self.s.diagnostics()), [])
      self.s.live_values()
      self.assertLess(time.perf_counter() - started, 5.0)


class RegistryTests(unittest.TestCase):
   """!Systems by id and by schema."""

   def test_lookup_and_refusals(self) -> None:
      """!The Sample flow is found by id and schema (dev only); a second system for one schema is refused.
      @return None
      """
      self.assertEqual(registry.for_schema(SCHEMA).system_id, "sample-flow")
      self.assertNotIn("sample-flow", [s.system_id for s in registry.systems(include_dev=False)])
      with self.assertRaises(ModelError):
         registry.get("nothing")

      class Twin(DesignerSystem):
         """!Another system for the same schema."""
         system_id = "twin"
         schema = SCHEMA

      with self.assertRaises(ModelError):
         registry.register(Twin())


class CommandLineTests(unittest.TestCase):
   """!`capsule-studio designer`."""

   def setUp(self) -> None:
      """!A temporary folder.
      @return None
      """
      ## Temporary folder.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_designer_cli_"))
      ## The manifest.
      self.file = str(self.root / "flow.json")

   def tearDown(self) -> None:
      """!Removes it.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def run_cli(self, *argv: str) -> tuple[int, str]:
      """!Runs a command.
      @param argv  its arguments
      @return exit status and output
      """
      out = io.StringIO()
      with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
         status = main(list(argv))
      return status, out.getvalue()

   def test_build_and_check_a_flow(self) -> None:
      """!Every edit the canvas makes, from the command line.
      @return None
      """
      f = self.file
      self.assertEqual(self.run_cli("designer", "new", f, "--system", "sample-flow")[0], 0)
      self.assertEqual(self.run_cli("designer", "new", f, "--system", "sample-flow")[0], 1)   # exists
      steps = [("add", f, "number", "--at", "0,0", "--set", "value=5"),
               ("add", f, "number", "--at", "0,120", "--set", "value=6"),
               ("add", f, "multiply", "--at", "240,40"),
               ("connect", f, "n1.value", "n3.a"), ("connect", f, "n2.value", "n3.b"),
               ("add-wired", f, "show", "--at", "480,40", "--from", "n3.result"),
               ("add", f, "note", "--at", "0,300", "--set", "text=Hello"),
               ("connect", f, "note1", "n3", "--label", "why"), ("label", f, "w1", "five"),
               ("set", f, "n1", "value=7"), ("move", f, "n1", "n2", "--by", "20,0"),
               ("resize", f, "note1", "--size", "200,100"), ("align", f, "left", "n1", "n2"),
               ("duplicate", f, "n1", "--offset", "0,400"), ("front", f, "n1"), ("back", f, "note1"),
               ("layout", f)]
      for step in steps:
         status, text = self.run_cli("designer", *step)
         self.assertEqual(status, 0, (step, text))
      status, text = self.run_cli("designer", "show", f)
      self.assertIn("n3: Multiply", text)
      self.assertIn("= 42", text)
      self.assertIn('c1: note1 -> n3 "why"', text)
      status, text = self.run_cli("designer", "show", f, "--json")
      data = json.loads(text)
      self.assertEqual(data["values"]["n4"], "42")
      self.assertEqual(self.run_cli("designer", "check", f), (0, "no problems\n"))
      self.assertEqual(self.run_cli("designer", "disconnect", f, "w2")[0], 0)
      status, text = self.run_cli("designer", "check", f)
      self.assertEqual(status, 1)
      self.assertIn("n3: b needs a wire", text)
      status, text = self.run_cli("designer", "set", f, "n1", "value=x")
      self.assertEqual(status, 1)
      self.assertIn("whole number", text)
      status, text = self.run_cli("designer", "remove", f, "nothing")
      self.assertEqual(status, 1)
      status, text = self.run_cli("designer", "kinds", f, "--from", "n3.result")
      self.assertIn("show: Show [Outputs]", text)
      self.assertNotIn("number:", text)
      status, text = self.run_cli("designer", "systems", "--all")
      self.assertIn("sample-flow: Sample flow (dev only)", text)


if __name__ == "__main__":
   unittest.main()
