#!/usr/bin/env python3
"""!Smoke tests of Logic > Bench (S9) with a fake runner (no build): the
scenario list and New, the scenario form's round trip and its edits (one
undo step each), the event list with draw markers and filters, a VM trace
row opening Logic > Effects at its source line, "Save as expected" with the
pass / fail check, cancelling, Run on save, and the page without a
toolchain. Skipped when PySide6 is missing; uses Qt's offscreen platform.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.core import bench, logic  # noqa: E402
from test_qt_battle import QtBattleTestCase, QtWidgets  # noqa: E402

## The Starter's move logic.
MOVES = "effects/moves.ceffect"
## The owner the VM records name.
OWNER = "move:Flare Claw"
## Lines below the owner's first line the recorded VM step is on (its `if target.alive and odds(10, 100) {`).
STEP_LINES = 10
## Its column.
STEP_COLUMN = 4
## A scenario using every part of the form.
RICH = {"schema": bench.SCHEMA, "name": "rich", "description": "every part", "format": "Double", "seed": 42,
        "no_escape": True, "field": {"weather": "Storm", "weather_turns": 3},
        "parties": [{"side": 0, "controller": "human", "flags": ["no_escape"],
                     "members": [{"species": "Emberkit", "level": 20, "item": "Focus Lens", "trait": "Fierce",
                                  "moves": ["Strike", "Flare Claw"], "seed": 9}]},
                    {"side": 1, "controller": "ai", "data": "Novice Kit"}],
        "pokes": [{"party": 1, "member": 0, "hp": 30, "status": "Scorch", "stages": {"defence": -2}},
                  {"party": 0, "member": 0, "volatiles": ["dazed"], "counters": {"dazed": 2}}],
        "choices": [{"move": "Flare Claw", "target": 2}, [{"move": 0}, "first"]],
        "answers": [{"learn_move": 1}], "stop": {"turns": 2}, "trace": {"vm": True}, "step_limit": 500}


def recorded(line: int) -> str:
   """!Bench output: two draws before "turn 1", a VM step of Flare Claw at a line of moves.ceffect, a stop.
   @param line  the VM step's line
   @return JSON lines
   """
   at = {"owner": "move Flare Claw", "hook": "hit", "program": 3, "pc": 4, "depth": 1, "file": MOVES,
         "line": line, "column": STEP_COLUMN}
   records = [{"t": "bench", "manifest": "battle.json", "rng": "default", "scenario": "wild"},
              {"t": "line", "text": "-- wild"},
              {"t": "rng", "n": 1, "value": 7, "turn": 1, "phase": "begin_turn"},
              {"t": "rng", "n": 2, "value": 3, "turn": 1, "phase": "act", **at},
              {"t": "line", "text": "turn 1"},
              {"t": "vm", "op": "between", "value": 3, **at},
              {"t": "event", "kind": "damage", "battler": 1, "target": 0, "extra": 0, "a": 5, "b": 0, "turn": 1},
              {"t": "line", "text": "> Hit 3 times!"},
              {"t": "vm", "op": "get", "owner": "volatile dazed", "hook": "turn_end", "program": 9, "pc": 1,
               "depth": 1, "file": "volatile dazed (template)", "line": 2, "column": 1},
              {"t": "stop", "reason": "end", "steps": 9, "turn": 1, "outcome": "Won", "draws": 2}]
   return "".join(json.dumps(r) + "\n" for r in records)


class FakeRunner:
   """!Stands in for core.bench.Runner: returns recorded output, or waits until cancelled.

   @var calls
   (scenario, rng, traces) of every run, shared by the runners a factory makes.
   """

   def __init__(self, output: str, calls: list[Any], block: bool = False) -> None:
      """!Creates the runner.
      @param output  JSON lines it returns
      @param calls   where runs are recorded
      @param block   wait for cancel() instead of returning
      """
      self.output = output
      self.calls = calls
      self.block = block
      self.cancelled = threading.Event()

   def build_and_run(self, project: Any, scenario: dict, rng: str, traces: list[str],
                     progress: bench.Progress) -> bench.BenchRun:
      """!A run.
      @param project   BattleProject
      @param scenario  the scenario's content
      @param rng       generator
      @param traces    traces
      @param progress  progress callback
      @return BenchRun
      """
      self.calls.append((scenario, rng, traces))
      progress(bench.PHASE_BUILD, "rebuilding")
      if self.block:
         self.cancelled.wait(30)
         raise bench.Cancelled("cancelled")
      return bench.BenchRun.from_output(self.output, rng=rng)

   def cancel(self) -> None:
      """!Cancels a blocked run.
      @return None
      """
      self.cancelled.set()


class BenchPanelTestCase(QtBattleTestCase):
   """!Helpers."""

   def bench_page(self, block: bool = False) -> tuple[Any, Any, list[Any]]:
      """!The battle editor on the Bench page with a scenario "wild", a fake runner and a toolchain.
      @param block  the fake runner waits for a cancel
      @return (BattleWindow, BenchPanel, the runner's calls)
      """
      w, panel = self.window("bench")
      calls: list[Any] = []
      row = next(r for r in logic.owners(w.project) if (r.kind, r.name) == ("move", "Flare Claw"))
      ## The VM step's line in moves.ceffect.
      self.step_line = row.line + STEP_LINES
      panel.runner_factory = lambda: FakeRunner(recorded(self.step_line), calls, block)
      panel.toolchain_check = lambda: []
      panel.check_toolchain()
      self.assertTrue(panel.new_scenario("wild"))
      self.settle()
      return w, panel, calls

   def run_panel(self, panel: Any, check: bool = False) -> None:
      """!Runs and waits for the run to end.
      @param panel  BenchPanel
      @param check  a Check run
      @return None
      """
      self.assertTrue(panel.run(check=check))
      self.assertTrue(panel.wait(10000))
      self.settle()

   def set_data(self, w: Any, panel: Any, data: dict) -> None:
      """!Replaces the selected scenario's content (one edit) and refreshes.
      @param w      BattleWindow
      @param panel  BenchPanel
      @param data   the content
      @return None
      """
      doc = panel.scenario_doc()
      self.assertTrue(w.run_edit("Set", lambda: bench.set_scenario(doc, data), doc))
      self.settle()


class ScenarioFormTests(BenchPanelTestCase):
   """!Scenario list, New, the form."""

   def test_migrate_offer(self) -> None:
      """!A scenario writing a retired poke key (C1: status_turns) shows Migrate scenarios; it renames the key as
      one undo step and the button goes.
      @return None
      """
      w, panel, _calls = self.bench_page()
      self.assertTrue(panel.migrate_button.isHidden())
      doc = panel.scenario_doc()
      data = json.loads(json.dumps(doc.data))
      data["pokes"] = [{"party": 1, "member": 0, "status_turns": 2}]
      self.set_data(w, panel, data)
      self.assertFalse(panel.migrate_button.isHidden())
      self.assertEqual(panel.migrate_scenarios(), ["bench/wild.json: pokes[0].status_turns -> status_counter"])
      self.settle()
      self.assertTrue(panel.migrate_button.isHidden())
      self.assertEqual(doc.data["pokes"], [{"party": 1, "member": 0, "status_counter": 2}])
      doc.undo()
      self.assertIn("status_turns", doc.data["pokes"][0])
      self.close(w)

   def test_new_and_list(self) -> None:
      """!New writes bench/NAME.json in the game folder and selects it; Undo / Save act on it.
      @return None
      """
      w, panel, _calls = self.bench_page()
      path = self.root / "bench" / "wild.json"
      self.assertTrue(path.is_file())
      self.assertEqual(panel.selected, path.resolve())
      self.assertEqual(panel.scenario_list.item(0).text(), "bench/wild.json")
      self.assertIs(w.document, panel.scenario_doc())
      self.assertEqual(panel.name_edit.text(), "wild")
      self.assertEqual(panel.party_table.rowCount(), 2)
      self.assertEqual(panel.party_table.item(0, 3).text(), "Novice Kit")
      from capsule_studio.ui.widgets import is_enabled
      self.assertFalse(is_enabled(panel.member_table))   # a party of the data: its members read only
      self.assertEqual(panel.member_table.item(0, 0).text(), "Sproutle")
      self.close(w)

   def test_round_trip(self) -> None:
      """!Every part of the form shows the scenario and reads it back unchanged (hidden keys kept).
      @return None
      """
      w, panel, _calls = self.bench_page()
      self.set_data(w, panel, RICH)
      self.assertEqual(panel.format_combo.currentText(), "Double")
      self.assertEqual(panel.weather_combo.currentText(), "Storm")
      self.assertEqual(panel.member_table.item(0, 4).text(), "Strike, Flare Claw")
      stages = [key for key, _kind in bench.POKE_COLUMNS].index("stages")
      self.assertEqual(panel.poke_table.item(0, stages).text(), "defence -2")
      self.assertEqual(panel.choices_edit.toPlainText(), "move Flare Claw @2\nmove 0 | first")
      self.assertEqual(panel.stop_combo.currentText(), "turns")
      self.assertTrue(panel.trace_checks["vm"].isChecked())
      self.assertEqual(panel.read_form(), RICH)
      self.assertFalse(panel.form_changed("Nothing"))   # the same content: no undo step
      self.assertEqual(panel.form_error.text(), "")      # it validates
      self.close(w)

   def test_edits(self) -> None:
      """!Form edits are one undo step each; a bad cell or choice says why and changes nothing; a party of the
      data becomes the party's own members when its data cell is cleared.
      @return None
      """
      w, panel, _calls = self.bench_page()
      doc = panel.scenario_doc()
      panel.seed_spin.setValue(77)
      panel.seed_spin.editingFinished.emit()
      self.settle()
      self.assertEqual(doc.data["seed"], 77)
      self.assertEqual(doc.undo_label(), "Scenario seed")
      panel.choices_edit.setPlainText("move 1\nswitch 1")
      panel.stop()
      self.assertEqual(doc.data["choices"], [{"move": 1}, {"switch": 1}])
      panel.choices_edit.setPlainText("fly away")
      panel.stop()
      self.assertIn("choices line 1", panel.form_error.text())
      self.assertEqual(doc.data["choices"], [{"move": 1}, {"switch": 1}])
      self.settle()
      panel.party_table.setCurrentCell(1, 0)
      self.settle()
      panel.party_table.item(1, 3).setText("")    # Scholar Wen's members become the party's own
      self.settle()
      self.assertNotIn("data", doc.data["parties"][1])
      self.assertEqual([m["species"] for m in doc.data["parties"][1]["members"]], ["Duskowl", "Glimmet", "Voltmink"])
      from capsule_studio.ui.widgets import is_enabled
      self.assertTrue(is_enabled(panel.member_table))
      panel.member_table.item(0, 1).setText("15")
      self.settle()
      self.assertEqual(doc.data["parties"][1]["members"][0]["level"], 15)
      self.assertEqual(doc.data["parties"][1]["members"][0]["item"], "Focus Lens")
      panel.member_table.item(0, 1).setText("lots")
      self.settle()
      self.assertIn("level: 'lots' is not a number", panel.form_error.text())
      self.assertTrue(panel.add_row("pokes"))
      self.settle()
      self.assertEqual(doc.data["pokes"], [{"party": 0, "member": 0}])
      self.assertTrue(w.undo_action.isEnabled())
      w.undo()
      self.settle()
      self.assertNotIn("pokes", doc.data)
      self.assertTrue(panel.save_scenario())
      self.assertEqual(json.loads(doc.path.read_text(encoding="utf-8"))["seed"], 77)
      self.close(w)


class RunTests(BenchPanelTestCase):
   """!Runs with the fake runner: events, traces, expected transcripts."""

   def test_event_list(self) -> None:
      """!The event list: draw markers on lines, type and text filters.
      @return None
      """
      # a reference checkout declaring a generator of its own (compat/generators.json, C1)
      ref = self.root / "rules"
      (ref / "templates").mkdir(parents=True)
      (ref / "compat").mkdir()
      (ref / "compat" / "random_alt.cpp").write_text("// a generator\n", encoding="utf-8")
      manifest = {"schema": bench.tool().GENERATORS_SCHEMA, "generators": [{"name": "alt", "source": "random_alt.cpp"}]}
      (ref / "compat" / bench.tool().GENERATORS_FILE).write_text(json.dumps(manifest), encoding="utf-8")
      reference = mock.patch.dict(os.environ, {"CAPSULE_REFERENCE": str(ref)})
      reference.start()
      self.addCleanup(reference.stop)
      w, panel, calls = self.bench_page()
      offered = [panel.rng_combo.itemText(i) for i in range(panel.rng_combo.count())]
      self.assertEqual(offered, [bench.DEFAULT_RNG, "alt"])
      panel.rng_combo.setCurrentText("alt")
      self.run_panel(panel)
      self.assertEqual(len(calls), 1)
      self.assertEqual(calls[0][1], "alt")
      self.assertEqual(calls[0][2], ["rng", "vm"])
      self.assertEqual(calls[0][0]["name"], "wild")
      self.assertIn("Ran with the alt generator: 3 transcript lines, 2 draws, 2 VM steps", panel.progress.text())
      kinds = [panel.event_list.topLevelItem(i).text(3) for i in range(panel.event_list.topLevelItemCount())]
      self.assertEqual(kinds, ["line", "rng", "rng", "line", "vm", "line", "vm", "stop"])   # events: off
      turn = panel.event_list.topLevelItem(3)
      self.assertEqual((turn.text(4), turn.text(2)), ("turn 1", "2"))   # two draws before the line
      panel.filter_checks["RNG"].setChecked(False)
      panel.filter_checks["Events"].setChecked(True)
      kinds = [panel.event_list.topLevelItem(i).text(3) for i in range(panel.event_list.topLevelItemCount())]
      self.assertEqual(kinds, ["line", "line", "vm", "event", "line", "vm", "stop"])
      panel.text_filter.setText("flare claw")
      self.assertEqual(panel.event_list.topLevelItemCount(), 1)
      self.close(w)

   def test_trace_opens_effects(self) -> None:
      """!Activating a VM row opens Logic > Effects on its owner, in the text view, at its line and column;
      template code says it has no source line.
      @return None
      """
      w, panel, _calls = self.bench_page()
      self.run_panel(panel)
      vm = [r.index for r in panel.last_run.events(["vm"])]
      self.assertTrue(panel.open_trace(vm[0]))
      self.settle()
      effects = w.active_panel()
      self.assertEqual(effects.panel_id, "effects")
      self.assertEqual(effects.owner, ("move", "Flare Claw"))
      self.assertEqual(effects.view_bar.currentIndex(), 1)   # the text view
      cur = effects.code.textCursor()
      self.assertEqual(cur.blockNumber() + 1, self.step_line)
      self.assertEqual(cur.positionInBlock() + 1, STEP_COLUMN)
      self.assertIn("odds(10, 100)", cur.block().text())
      w.show_panel("bench")
      self.assertFalse(panel.open_trace(vm[1]))    # template code
      self.assertFalse(panel.open_trace(0))        # the header: no owner
      self.close(w)

   def test_expected_check(self) -> None:
      """!Save as expected writes the transcript beside the scenario; Check passes, then fails on a change.
      @return None
      """
      w, panel, _calls = self.bench_page()
      self.assertFalse(panel.check_button.isEnabled())   # no expected transcript yet
      self.run_panel(panel)
      self.assertTrue(panel.expect_button.isEnabled())
      self.assertTrue(panel.save_expected())
      self.settle()
      expected = self.root / "bench" / "wild.expected.txt"
      self.assertEqual(expected.read_text(encoding="utf-8"), "-- wild\nturn 1\n> Hit 3 times!\n")
      saved = json.loads((self.root / "bench" / "wild.json").read_text(encoding="utf-8"))
      self.assertEqual(saved["expect"], "wild.expected.txt")
      self.assertTrue(panel.check_button.isEnabled())
      self.assertTrue(panel.check_label.text().startswith("PASS"))
      expected.write_text("-- wild\nturn 2\n> Hit 3 times!\n", encoding="utf-8")
      self.run_panel(panel, check=True)
      self.assertTrue(panel.check_label.text().startswith("FAIL: wild.expected.txt:2"))
      self.assertIn("expected: turn 2", panel.check_label.text())
      self.close(w)

   def test_cancel_and_run_on_save(self) -> None:
      """!Cancel stops a run; with Run on save a save of the scenario runs it.
      @return None
      """
      w, panel, calls = self.bench_page(block=True)
      self.assertTrue(panel.run())
      self.assertFalse(panel.run_button.isEnabled())
      self.assertTrue(panel.cancel_button.isEnabled())
      panel.cancel()
      self.assertTrue(panel.wait(10000))
      self.assertEqual(panel.progress.text(), "Cancelled.")
      self.assertTrue(panel.run_button.isEnabled())
      panel.runner_factory = lambda: FakeRunner(recorded(self.step_line), calls)
      panel.run_on_save.setChecked(True)
      panel.seed_spin.setValue(5)
      panel.seed_spin.editingFinished.emit()
      self.settle()
      self.assertEqual(len(calls), 1)            # an edit does not run
      self.assertTrue(panel.save_scenario())
      for _ in range(50):
         self.settle()
         if panel.job is not None:
            break
         QtWidgets.QApplication.processEvents()
         threading.Event().wait(0.02)
      self.assertTrue(panel.wait(10000))
      self.assertEqual(len(calls), 2)
      self.assertEqual(calls[1][0]["seed"], 5)
      self.close(w)

   def test_close_while_running(self) -> None:
      """!Closing the window during a run keeps the thread until it ends; quitting cancels it.
      @return None
      """
      from capsule_studio.ui.editors.logic import bench_panel
      w, panel, _calls = self.bench_page(block=True)
      self.assertTrue(panel.run())
      job = panel.job
      self.close(w)
      w.deleteLater()
      self.settle()
      self.assertIn(job, bench_panel._RUNNING)
      bench_panel.finish_jobs()
      self.settle()
      self.assertTrue(job.isFinished())
      self.assertEqual(bench_panel._RUNNING, set())

   def test_no_toolchain(self) -> None:
      """!Without CMake or a compiler the page says what is needed, Run is off, and editing still works.
      @return None
      """
      w, panel, calls = self.bench_page()
      panel.toolchain_check = lambda: ["CMake 3.24 or newer (cmake on PATH)"]
      panel.check_toolchain()
      self.assertFalse(panel.banner.isHidden())
      self.assertIn("building it needs CMake 3.24", panel.banner.text())
      self.assertFalse(panel.run_button.isEnabled())
      self.assertFalse(panel.run())
      self.assertEqual(calls, [])
      panel.seed_spin.setValue(3)
      panel.seed_spin.editingFinished.emit()
      self.settle()
      self.assertEqual(panel.scenario_doc().data["seed"], 3)
      panel.toolchain_check = lambda: []
      panel.check_toolchain()
      self.assertTrue(panel.banner.isHidden())
      self.assertTrue(panel.run_button.isEnabled())
      self.close(w)
