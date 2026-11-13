#!/usr/bin/env python3
"""!Tests for plugin data (capsule_studio.core.plugin_data, D-10 §4), plugin API 3 (connectors, designer systems,
file formats, previews) and the studio's plugin data extension (validator, `capsule-studio ext`); no Qt needed.

Uses a copy of the engine's map sandbox (with the Starter sample its world names beside it) that lists the engine's
sample plugin (samples/plugins/party_moods: a connector and a Studio extension with a CSV format and a preview).
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import engine, plugin_data  # noqa: E402
from capsule_studio.core.world import Project  # noqa: E402
from capsule_studio.plugins import loader, registry  # noqa: E402
from sample_data import copy_engine_apps  # noqa: E402

## The sample plugin's id.
SAMPLE_ID = "sample.party_moods"
## The engine's sample plugin, relative to the engine checkout.
SAMPLE = ("samples", "plugins", "party_moods")
## The game's folder of plugins.
PLUGIN_FOLDER = "plugins/party_moods"
## A party of the Starter.
PARTY = "Novice Kit"
## Another one.
OTHER_PARTY = "Scholar Wen"


def run_cli(*argv: str) -> tuple[int, str]:
   """!Runs the CLI.
   @param argv  arguments
   @return (exit status, stdout + stderr)
   """
   out, err = io.StringIO(), io.StringIO()
   with redirect_stdout(out), redirect_stderr(err):
      try:
         status = cli(list(argv))
      except SystemExit as e:
         status = int(e.code or 0)
   return status, out.getvalue() + err.getvalue()


def read_json(path: Path) -> Any:
   """!Reads JSON.
   @param path  the file
   @return the data
   """
   return json.loads(path.read_text(encoding="utf-8"))


def make_game(root: Path) -> Path:
   """!The map sandbox, listing the sample plugin.
   @param root  a temporary folder
   @return the game's reference/project.json
   """
   game = copy_engine_apps(root, ["sandbox_map"], ("data", "reference")) / "sandbox_map"
   shutil.copytree(engine.root().joinpath(*SAMPLE), game / PLUGIN_FOLDER,
                   ignore=shutil.ignore_patterns("__pycache__"))
   project = game / "reference" / "project.json"
   data = read_json(project)
   data["plugins"] = [PLUGIN_FOLDER]
   project.write_text(json.dumps(data, indent=1), encoding="utf-8")
   return project


class PluginDataWorld(unittest.TestCase):
   """!A copied game with the sample plugin."""

   def setUp(self) -> None:
      """!Copies the game.
      @return None
      """
      ## Temporary root.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_plugin_data_"))
      ## The project manifest.
      self.project = make_game(self.root)
      ## The game folder.
      self.game = self.project.parent.parent
      ## The world.
      self.world = self.game / "data" / "world.json"
      ## The battle manifest.
      self.battle = self.root / "samples" / "starter" / "battle.json"

   def tearDown(self) -> None:
      """!Removes the copy and the plugins' private modules.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)
      for name in [n for n in sys.modules if n.startswith(("capsule_connector_", "_capsule_plugin_sample"))]:
         del sys.modules[name]


class CoreTests(PluginDataWorld):
   """!core.plugin_data on files and on a Project."""

   def test_schema_records_and_edits(self) -> None:
      """!The connector's points and schemas, the records, new blocks, setting and removing blocks, the checks.
      @return None
      """
      data, store = plugin_data.for_files(self.project)
      self.assertEqual([p.plugin_id for p in data.plugins()], [SAMPLE_ID])
      self.assertEqual(data.points(SAMPLE_ID), ["party", "map", "cell"])
      fields = data.schema(SAMPLE_ID, "party")["fields"]
      self.assertEqual(fields["mood"]["choices"], ["calm", "angry", "cheerful"])
      self.assertIn(PARTY, [t.name for t in data.targets("party")])
      self.assertIn(OTHER_PARTY, data.names("party"))
      self.assertEqual(data.new_block(SAMPLE_ID, "party"), {})
      self.assertEqual(data.new_block(SAMPLE_ID, "cell"), {"mood": "calm"})
      self.assertEqual(data.complete(SAMPLE_ID, "party", {}), {"mood": "calm", "bonus": 0, "rival": None})
      self.assertTrue(data.problems(SAMPLE_ID, "party", {"mood": "sad"}))
      with self.assertRaises(plugin_data.PluginDataError):
         data.schema(SAMPLE_ID, "asset")
      with self.assertRaises(plugin_data.PluginDataError):
         data.plugin("acme.none")

      self.assertTrue(data.set(SAMPLE_ID, "party", PARTY, {"mood": "angry", "rival": PARTY}))
      self.assertTrue(data.set(SAMPLE_ID, "cell", "cave@-3,-4", {"mood": "cheerful"}))
      self.assertEqual(data.records(SAMPLE_ID, "party"), [PARTY])
      self.assertEqual(data.records(SAMPLE_ID, "cell"), ["cave@-3,-4"])
      self.assertEqual(data.cells(SAMPLE_ID, "cave"), [(-3, -4)])
      # The check reads the open (unsaved) documents: its own rival is the sample's error.
      errors = [p.message for p in data.check().errors()]
      self.assertTrue(any("its own rival" in m for m in errors), errors)
      self.assertEqual([(d.level, d.plugin) for d in data.diagnostics("cave")], [])
      self.assertEqual([d.plugin for d in data.diagnostics()], [SAMPLE_ID])
      data.set(SAMPLE_ID, "party", PARTY, {"mood": "angry", "rival": OTHER_PARTY})
      self.assertEqual(data.check().errors(), [])
      self.assertEqual(sorted(p.name for p in store.save()), ["battle.json", "cave.json"])
      self.assertEqual(read_json(self.battle)["parties"][0]["ext"], {SAMPLE_ID: {"mood": "angry",
                                                                              "rival": OTHER_PARTY}})
      # Removing it leaves the files without "ext".
      data.set(SAMPLE_ID, "party", PARTY, None)
      data.set(SAMPLE_ID, "cell", "cave@-3,-4", None)
      store.save()
      self.assertNotIn("ext", read_json(self.battle)["parties"][0])
      self.assertNotIn("cell_ext", read_json(self.game / "data" / "maps" / "cave.json"))

   def test_cell_diagnostics_name_the_map_and_cell(self) -> None:
      """!A cell's error shows on its map at its cell, not on other maps.
      @return None
      """
      data, _store = plugin_data.for_files(self.project)
      data.set(SAMPLE_ID, "cell", "cave@-3,-4", {"mood": "sad"})
      found = data.diagnostics("cave")
      self.assertEqual([(d.level, d.map, d.at, d.plugin) for d in found], [("error", "cave", (-3, -4), SAMPLE_ID)])
      other = [m for m in Project.open(self.world).map_names() if m != "cave"][0]
      self.assertEqual(data.diagnostics(other), [])

   def test_project_store_shares_the_studio_documents(self) -> None:
      """!On a Project the edits go to its own Documents (the map editor's), so undo and dirty marks are shared.
      @return None
      """
      project = Project.open(self.world)
      data = plugin_data.for_project(project)
      self.assertIsNotNone(data)
      data.set(SAMPLE_ID, "map", "cave", {"music_mood": "cheerful"})
      cave = project.map("cave")
      self.assertEqual(cave.data["ext"], {SAMPLE_ID: {"music_mood": "cheerful"}})
      self.assertTrue(cave.dirty)
      self.assertTrue(cave.undo())
      self.assertNotIn("ext", cave.data)
      # A battle entry's file opens beside the world, and saves with it.
      data.set(SAMPLE_ID, "party", PARTY, {"mood": "angry"})
      battle = project.document(self.battle, "capsule.battle/1")
      self.assertTrue(battle.dirty)
      project.save_all()
      self.assertEqual(read_json(self.battle)["parties"][0]["ext"], {SAMPLE_ID: {"mood": "angry"}})
      # A page of the Studio holding the file: its Document is the one edited.
      shared = project.document(self.battle, "capsule.battle/1")
      # Stores ask with resolved paths (Windows' short temp names resolve to long ones).
      battle = self.battle.resolve()
      other = plugin_data.for_project(Project.open(self.world), lambda path: shared if path == battle else None)
      other.set(SAMPLE_ID, "party", OTHER_PARTY, {"mood": "calm"})
      self.assertEqual(shared.data["parties"][1]["ext"], {SAMPLE_ID: {"mood": "calm"}})

   def test_formats_and_previews(self) -> None:
      """!The sample's CSV format round trips (an import is one undo step over its files) and its preview renders.
      @return None
      """
      reg = registry.Registry()
      self.assertEqual(loader.load_folders(reg, [self.game / PLUGIN_FOLDER]), [SAMPLE_ID])
      fmt = reg.find("format", "moods-csv")
      preview = reg.find("preview", f"{SAMPLE_ID}/mood")
      self.assertEqual((fmt.plugin, fmt.can_export(), fmt.can_import()), (SAMPLE_ID, True, True))
      project = Project.open(self.world)
      data = plugin_data.for_project(project)
      data.set(SAMPLE_ID, "party", PARTY, {"mood": "angry", "bonus": 4})
      text = data.export(fmt)
      self.assertIn(f"{PARTY},angry,4,", text)
      self.assertIn(f"{OTHER_PARTY},,,", text)
      changes = data.import_changes(fmt, f"party,mood,bonus,rival\n{PARTY},,,\n{OTHER_PARTY},cheerful,2,{PARTY}\n")
      self.assertEqual(changes, [("party", PARTY, None), ("party", OTHER_PARTY, {"mood": "cheerful", "bonus": 2,
                                                                                   "rival": PARTY})])
      self.assertEqual(data.apply(SAMPLE_ID, changes, "Import moods"), 2)
      battle = project.document(self.battle, "capsule.battle/1")
      self.assertEqual(data.records(SAMPLE_ID, "party"), [OTHER_PARTY])
      self.assertTrue(battle.undo())   # the import is one step
      self.assertEqual(data.records(SAMPLE_ID, "party"), [PARTY])
      with self.assertRaises(plugin_data.PluginDataError):
         data.import_changes(fmt, f"party,mood,bonus,rival\n{PARTY},sad,,\n")
      with self.assertRaises(plugin_data.PluginDataError):
         data.import_changes(fmt, "who,what\nx,y\n")
      shown = data.complete(SAMPLE_ID, "party", data.get(SAMPLE_ID, "party", PARTY))
      self.assertEqual(preview.render(data, "party", PARTY, shown), f"{PARTY} fights angry.\nThe AI adds 4 to its "
                                                                   "scores.")


class PluginHostTests(PluginDataWorld):
   """!Loading plugins with connectors, and the API 3 registration points."""

   def plugin(self, pid: str, files: dict[str, str], **keys: Any) -> Path:
      """!Writes a plugin folder.
      @param pid    its id
      @param files  {relative path: text}
      @param keys   plugin.json overrides
      @return its folder
      """
      folder = self.root / pid
      data = {"schema": "capsule.plugin/1", "id": pid, "version": "2026.11.12.1080", "api": registry.API,
              "extension": {"module": "ext.extension"}}
      data.update(keys)
      folder.mkdir(parents=True)
      (folder / "plugin.json").write_text(json.dumps(data), encoding="utf-8")
      for rel, text in {"ext/__init__.py": "", **files}.items():
         (folder / rel).parent.mkdir(parents=True, exist_ok=True)
         (folder / rel).write_text(textwrap.dedent(text), encoding="utf-8")
      return folder

   def test_connectors_load(self) -> None:
      """!A plugin with a connector loads (with or without an extension); the engine's refusals refuse it.
      @return None
      """
      reg = registry.Registry()
      self.assertEqual(loader.load_folders(reg, [self.game / PLUGIN_FOLDER]), [SAMPLE_ID])
      self.assertEqual(reg.connectors(), [SAMPLE_ID])
      connector = "def register(c):\n    c.attach('map', c.block(x=c.integer(0, 3, default=0)))\n"
      only = self.plugin("acme.only", {"ext/connector.py": connector}, extension=None,
                         connector={"module": "ext.connector"})
      self.assertEqual(loader.load_folders(reg, [only]), ["acme.only"])
      cases = [
         (self.plugin("acme.old", {"ext/connector.py": connector}, api=2, extension=None,
                      connector={"module": "ext.connector"}), "needs plugin API 3"),
         (self.plugin("acme.nowhere", {"ext/connector.py": "def register(c):\n    pass\n"}, extension=None,
                      connector={"module": "ext.connector"}), "attaches nowhere"),
         (self.plugin("acme.qt", {"ext/connector.py": "import PySide6\n" + connector}, extension=None,
                      connector={"module": "ext.connector"}), "imports PySide6"),
      ]
      for folder, needle in cases:
         r = registry.Registry()
         self.assertEqual(loader.load_folders(r, [folder]), [], needle)
         self.assertIn(needle, r.errors[0][1])
         self.assertEqual(r.plugins, {})

   def test_api3_registrations(self) -> None:
      """!Designer systems, formats and previews register with the plugin's prefix; older plugins cannot.
      @return None
      """
      body = """
         from capsule_studio.plugins.registry import FileFormat, Preview

         class Out(FileFormat):
             id = "out"
             suffix = ".txt"
             def export_data(self, data):
                 return "x"

         class Look(Preview):
             id = "look"
             attach_points = ("map",)
             def render(self, data, attach, name, block):
                 return name

         def register(ctx):
             ctx.add_designer_system("ai", "AI", lambda: "system")
             ctx.add_format(Out())
             ctx.add_preview(Look())
         """
      reg = registry.Registry()
      self.assertEqual(loader.load_folders(reg, [self.plugin("acme.new", {"ext/extension.py": body})]),
                       ["acme.new"])
      self.assertEqual([(d.system_id, d.title, d.factory()) for d in reg.designer_systems()],
                       [("acme.new/ai", "AI", "system")])
      self.assertEqual([(f.id, f.plugin, f.can_export(), f.can_import()) for f in reg.formats()],
                       [("acme.new/out", "acme.new", True, False)])
      self.assertEqual([p.id for p in reg.previews("acme.new", "map")], ["acme.new/look"])
      self.assertEqual(reg.previews("acme.new", "cell"), [])
      self.assertIs(reg.find("format", "out"), reg.formats()[0])
      old = registry.Registry()
      self.assertEqual(loader.load_folders(old, [self.plugin("acme.older", {"ext/extension.py": body}, api=2)]), [])
      self.assertIn("need plugin API 3", old.errors[0][1])

   def test_builtin_panel_shows_with_connectors(self) -> None:
      """!The Plugin data panel is a built-in panel shown only while a plugin with a connector is loaded.
      @return None
      """
      reg = loader.builtin_registry().copy()
      self.assertEqual(reg.errors, [])
      self.assertNotIn("plugin-data", [s.panel_id for s in reg.panels(registry.STUDIO_HOSTS)])
      loader.load_project_plugins(reg, self.world)
      self.assertIn("plugin-data", [s.panel_id for s in reg.panels(registry.STUDIO_HOSTS)])
      self.assertIn("plugin-data", [s.panel_id for s in reg.panels(registry.MAP_EDITOR)])


class CommandTests(PluginDataWorld):
   """!`capsule-studio ext ...` and the validator in `world validate`."""

   def ext(self, *argv: str) -> tuple[int, str]:
      """!Runs an ext command on the game.
      @param argv  the command and its arguments
      @return (status, output)
      """
      return run_cli("--project", str(self.project), "ext", *argv)

   def test_commands(self) -> None:
      """!points, plugins, targets, set, show, list, check, preview, formats, export, import, remove.
      @return None
      """
      status, out = run_cli("ext", "points")
      self.assertEqual(status, 0, out)
      self.assertIn("cell: a map file", out)
      status, out = run_cli("ext", "check")
      self.assertEqual(status, 1)
      self.assertIn("--project", out)
      status, out = self.ext("plugins")
      self.assertIn("cell: mood (choice, required)", out)
      status, out = self.ext("targets", "party")
      self.assertIn(PARTY, out)
      status, out = self.ext("set", SAMPLE_ID, "party", PARTY, "--field", "mood=angry", "--field", "bonus=4")
      self.assertEqual(status, 0, out)
      self.assertEqual(read_json(self.battle)["parties"][0]["ext"], {SAMPLE_ID: {"mood": "angry", "bonus": 4}})
      status, out = self.ext("set", SAMPLE_ID, "party", PARTY, "--field", "mood=sad")
      self.assertEqual(status, 1)
      self.assertIn("one of calm, angry, cheerful", out)
      status, out = self.ext("set", SAMPLE_ID, "party", PARTY, "--field", f"rival={PARTY}")
      self.assertEqual(status, 1)
      self.assertIn("not saved", out)
      self.assertNotIn("rival", read_json(self.battle)["parties"][0]["ext"][SAMPLE_ID])
      status, out = self.ext("set", SAMPLE_ID, "cell", "cave@99,99", "--field", "mood=calm")
      self.assertEqual(status, 1)
      self.assertIn("outside the map's chunks", out)
      status, out = self.ext("show", SAMPLE_ID, "party", PARTY, "--complete")
      self.assertEqual(json.loads(out), {"mood": "angry", "bonus": 4, "rival": None})
      status, out = self.ext("list")
      self.assertIn(f"{SAMPLE_ID} party {PARTY}:", out)
      status, out = self.ext("check")
      self.assertEqual(status, 0, out)
      self.assertIn("1 connector(s), 1 block(s), 0 error(s)", out)
      status, out = self.ext("preview", "mood", "party", PARTY)
      self.assertIn(f"{PARTY} fights angry.", out)
      status, out = self.ext("formats")
      self.assertIn(f"format {SAMPLE_ID}/moods-csv", out)
      sheet = self.root / "moods.csv"
      status, out = self.ext("export", "moods-csv", str(sheet))
      self.assertEqual(status, 0, out)
      self.assertIn(f"{PARTY},angry,4,", sheet.read_text(encoding="utf-8"))
      sheet.write_text(f"party,mood,bonus,rival\n{PARTY},,,\n{OTHER_PARTY},calm,,\n", encoding="utf-8")
      status, out = self.ext("import", "moods-csv", str(sheet), "--dry-run")
      self.assertEqual(status, 0, out)
      self.assertIn("ext", read_json(self.battle)["parties"][0])
      status, out = self.ext("import", "moods-csv", str(sheet))
      self.assertEqual(status, 0, out)
      self.assertNotIn("ext", read_json(self.battle)["parties"][0])
      status, out = self.ext("remove", SAMPLE_ID, "party", OTHER_PARTY)
      self.assertEqual(status, 0, out)
      status, out = self.ext("remove", SAMPLE_ID, "party", OTHER_PARTY)
      self.assertEqual(status, 1)

   def test_world_validate_reports_connector_errors(self) -> None:
      """!The plugin data validator runs in world validate, naming the plugin.
      @return None
      """
      _status, _out = self.ext("set", SAMPLE_ID, "map", "cave", "--field", "music_mood=calm")
      cave = self.game / "data" / "maps" / "cave.json"
      data = read_json(cave)
      data["ext"][SAMPLE_ID]["music_mood"] = "sad"
      cave.write_text(json.dumps(data), encoding="utf-8")
      status, out = run_cli("--project", str(self.project), "world", "validate", str(self.world))
      self.assertEqual(status, 1, out)
      self.assertIn(f"[{SAMPLE_ID}]", out)
      self.assertIn("one of calm, angry, cheerful", out)


if __name__ == "__main__":
   unittest.main()
