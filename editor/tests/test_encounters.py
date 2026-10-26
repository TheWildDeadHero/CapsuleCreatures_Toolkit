#!/usr/bin/env python3
"""!Tests for wild encounter editing (capsule_studio.core.encounters), the
plugin host (capsule_studio.plugins) and the studio's encounter extension:
its commands, map tool, overlay, hover text and validator (no Qt needed).

Uses the engine's map sandbox world (copied, with the Starter sample its world
names beside it, as in the engine's layout: tests/sample_data.copy_engine_apps).
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import textwrap
import unittest
import warnings
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import encounters as enc  # noqa: E402
from capsule_studio.core import engine, maps  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.world import Project  # noqa: E402
from capsule_studio.plugins import MapView, loader, manifest, purity, registry, versions  # noqa: E402
from sample_data import copy_engine_apps  # noqa: E402

## The engine's apps folder.
APPS = None


def apps() -> Path:
   """!The engine's apps folder.
   @return Path
   """
   return engine.root() / "apps"


class EncounterWorld(unittest.TestCase):
   """!Base: a copy of the sandbox world (and the battle data it names) per test.

   @var root
   Temporary apps folder (sandbox_map/data inside; the Starter it names in ../samples/starter).
   @var dir
   The world's folder.
   @var project
   The opened Project.
   """

   def setUp(self) -> None:
      """!Copies and opens the world.
      @return None
      """
      self.root = copy_engine_apps(Path(tempfile.mkdtemp(prefix="capsule_enc_")), ["sandbox_map"])
      self.dir = self.root / "sandbox_map" / "data"
      self.project = Project.open(self.dir / "world.json")

   def tearDown(self) -> None:
      """!Removes the copy.
      @return None
      """
      shutil.rmtree(self.root.parent, ignore_errors=True)

   def run_cli(self, *args: object) -> tuple[int, str]:
      """!Runs capsule-studio.
      @param args  arguments
      @return (status, stdout)
      """
      out, err = io.StringIO(), io.StringIO()
      with redirect_stdout(out), redirect_stderr(err):
         status = cli([str(a) for a in args])
      return status, out.getvalue() + err.getvalue()

   def reopen(self) -> Project:
      """!Opens the saved world again.
      @return Project
      """
      return Project.open(self.dir / "world.json")


class CoreTests(EncounterWorld):
   """!core.encounters on the sandbox world."""

   def test_reads_the_world(self) -> None:
      """!Methods, conditions, species (in the battle compiler's order), files and slots.
      @return None
      """
      p = self.project
      self.assertEqual(enc.method_names(p), ["walk", "swim"])
      self.assertEqual(enc.step_methods(p), ["walk", "swim"])
      self.assertEqual(enc.conditions(p), ["night"])
      names, level_max = enc.species(p)
      bc = engine.tool("battle_compiler")
      self.assertEqual(names, [s["name"] for s in bc.compile_battle(enc.battle_path(p))["species"]])
      self.assertEqual(level_max, bc.compile_battle(enc.battle_path(p))["rules"]["level_max"])   # the sample's
      self.assertEqual(enc.map_file(p, "cave"), None)
      self.assertEqual(enc.map_file(p, "showcase"), (self.dir / "encounters/showcase.json").resolve())
      cells = enc.slot_cells(p.map("showcase").data)
      self.assertEqual(sorted(cells), [0, 1])
      self.assertEqual(len(cells[0]) + len(cells[1]), 48)
      self.assertIn("Sproutle", enc.describe_slot(p, "showcase", 0))
      self.assertIn("no encounter table", enc.describe_slot(p, "showcase", 5))

   def test_shares_match_the_engine(self) -> None:
      """!Shares under conditions use the engine's filtering and truncating Q8 multipliers.
      @return None
      """
      p = self.project
      t = enc.tables(enc.map_doc(p, "showcase"))[0]   # Sproutle 45, Clodbun 30, Voltmink 25 (night x1/2)
      day = [w for _e, w, _s in enc.shares(p, t)]
      night = [w for _e, w, _s in enc.shares(p, t, ["night"])]
      self.assertEqual(day, [45, 30, 25])
      self.assertEqual(night, [45, 30, 12])   # 25 * 128 >> 8
      self.assertAlmostEqual(sum(s for _e, _w, s in enc.shares(p, t)), 1.0)
      shared = enc.tables(enc.map_doc(p, "meadow"))[0]
      self.assertEqual([w for _e, w, _s in enc.shares(p, shared)], [50, 35, 15, 0])

   def test_new_file_and_tables(self) -> None:
      """!A map gets a file on first use; tables, entries and rates are checked; compiles with unsaved edits.
      @return None
      """
      p = self.project
      doc = enc.map_doc(p, "cave", create=True)
      self.assertEqual(p.map("cave").data["encounters"], "../encounters/cave.json")
      self.assertEqual(list(doc.data), ["schema", "id", "tables"])
      with doc.edit("Add table"):
         i = enc.add_table(doc, 0, "walk", "1/12", "Cave floor")
         enc.add_entry(doc, i, "Clodbun", [8, 10], 3, modifiers=[{"when": "night", "multiply": 2}])
         enc.add_entry(doc, i, "Duskowl", 9, 1, requires=["night"])
      with self.assertRaises(DocumentError):
         enc.add_table(doc, 0, "walk")
      with self.assertRaises(DocumentError):
         enc.check_rate("3/2")
      with doc.edit("x"):
         with self.assertRaises(DocumentError):
            enc.set_entry(doc, 0, 1, excludes=["night"])
      self.assertIsNone(p.validate())
      with doc.edit("Bad species"):
         enc.set_entry(doc, 0, 0, species_name="Nobody")
      self.assertIn("unknown species 'Nobody'", p.validate())
      doc.undo()
      p.save_all()
      q = self.reopen()
      self.assertEqual(enc.tables(enc.map_doc(q, "cave"))[0]["entries"][0]["levels"], [8, 10])
      self.assertEqual(enc.format_rate("1/12"), "1/12 (8.33%)")

   def test_shared_tables_link_and_rename(self) -> None:
      """!Linking, copying a shared table in, renames following references, removal refused while used.
      @return None
      """
      p = self.project
      s = enc.shared_doc(p)
      doc = enc.map_doc(p, "showcase")
      with doc.edit("Link"):
         enc.link_shared(doc, 1, "meadow_grass")
      self.assertEqual([e["species"] for e in enc.resolved(p, enc.tables(doc)[1])[1]],
                       ["Sproutle", "Breezle", "Voltmink", "Duskowl"])
      with self.assertRaises(DocumentError):
         enc.entries(doc, 1)
      self.assertEqual(enc.rename(p, "shared", "meadow_grass", "grass"), 3)
      self.assertEqual(enc.tables(enc.map_doc(p, "meadow"))[0]["table"], "grass")
      self.assertEqual(enc.tables(doc)[1]["table"], "grass")
      with self.assertRaises(DocumentError):
         enc.remove(p, "shared", "grass")
      with doc.edit("Unlink"):
         enc.unlink_shared(p, doc, 1)
      self.assertEqual(len(enc.tables(doc)[1]["entries"]), 4)
      self.assertEqual(enc.tables(doc)[1]["rate"], "1/10")
      with s.edit("Add"):
         enc.add_shared(s, "spare", "1/2")
      enc.remove(p, "shared", "spare")
      self.assertIsNone(enc.find_shared(p, "spare"))
      self.assertIsNone(p.validate())

   def test_methods_and_conditions(self) -> None:
      """!Adding, editing, renaming everywhere, removal refused while used.
      @return None
      """
      p = self.project
      with p.world.edit("Add"):
         enc.add_method(p.world, "old lure", "script")
         enc.add_condition(p.world, "rain")
      with p.world.edit("x"):
         with self.assertRaises(DocumentError):
            enc.set_method(p.world, "old lure", vehicles=["foot"])
         with self.assertRaises(DocumentError):
            enc.add_method(p.world, "walk")
      with p.world.edit("Edit"):
         enc.set_method(p.world, "swim", vehicles=None)
      self.assertNotIn("vehicles", enc.methods(p)[1])
      enc.rename(p, "condition", "night", "dark")
      mods = enc.tables(enc.map_doc(p, "showcase"))[0]["entries"][2]["modifiers"]
      self.assertEqual(mods[0]["when"], "dark")
      self.assertEqual(enc.find_shared(p, "meadow_grass")["entries"][3]["requires"], ["dark"])
      enc.rename(p, "method", "walk", "grass")
      self.assertEqual({t["method"] for t in enc.tables(enc.map_doc(p, "showcase"))}, {"grass"})
      with self.assertRaises(DocumentError):
         enc.remove(p, "method", "grass")
      with self.assertRaises(DocumentError):
         enc.remove(p, "condition", "dark")
      enc.remove(p, "condition", "rain")
      enc.remove(p, "method", "old lure")
      self.assertEqual(enc.method_names(p), ["grass", "swim"])
      self.assertIsNone(p.validate())

   def test_diagnostics(self) -> None:
      """!Cells in slots without a step table, tables without cells, empty tables, unused shared tables.
      @return None
      """
      p = self.project
      doc = p.map("cave")
      x, y = next((cx * 8 + x, cy * 8 + y) for c in doc.data["chunks"] for cx, cy in [c["at"]]
                  for y, row in enumerate(c["cells"]) for x, v in enumerate(row) if v is not None)
      with doc.edit("Encounters"):
         maps.set_attributes(doc, x, y, encounter=True, slot=4)
      found = enc.diagnostics(p, "cave")
      self.assertEqual([(d.level, d.at) for d in found], [("warning", (x, y))])
      e = enc.map_doc(p, "cave", create=True)
      with e.edit("Add"):
         enc.add_table(e, 4, "walk")
         enc.add_table(e, 6, "walk")
      found = {d.message for d in enc.diagnostics(p, "cave")}
      self.assertTrue(any("slot 6 has no encounter cells" in m for m in found), found)
      self.assertTrue(any("no entries" in m for m in found), found)
      s = enc.shared_doc(p)
      with s.edit("Add"):
         enc.add_shared(s, "spare")
      self.assertTrue(any("'spare' is used by no map" in d.message for d in enc.diagnostics(p)))

   def test_modifier_text(self) -> None:
      """!Modifier text round-trips.
      @return None
      """
      mods = enc.parse_modifiers("rain x0, night x2.5, swarm x1/2")
      self.assertEqual(mods, [{"when": "rain", "multiply": 0}, {"when": "night", "multiply": 2.5},
                              {"when": "swarm", "multiply": "1/2"}])
      self.assertEqual(enc.format_modifiers(mods), "rain x0, night x2.5, swarm x1/2")
      with self.assertRaises(DocumentError):
         enc.parse_modifiers("rain")

   def test_import_brings_encounters(self) -> None:
      """!Importing a map brings its encounter tables (shared ones inline), methods, conditions and battle data.
      @return None
      """
      target = Project.create(self.root / "fresh" / "world.json", "fresh")
      lines = target.import_from(self.dir / "world.json", maps=["meadow"])
      self.assertTrue(any(line.startswith("encounters: tables of meadow") for line in lines), lines)
      self.assertEqual(enc.method_names(target), ["step", "walk"])
      self.assertEqual(enc.conditions(target), ["night"])
      self.assertEqual(target.world.data["battle"], "../../samples/starter/battle.json")   # the Starter beside apps/
      t = enc.tables(enc.map_doc(target, "meadow"))[0]
      self.assertNotIn("table", t)
      self.assertEqual(len(t["entries"]), 4)
      self.assertIsNone(target.validate())
      target.save_all()
      self.assertTrue((self.root / "fresh" / "encounters" / "meadow.json").is_file())


class PluginHostTests(unittest.TestCase):
   """!capsule_studio.plugins: versions, manifests, the pure-Python rule, loading, registration."""

   def setUp(self) -> None:
      """!A scratch folder for plugins.
      @return None
      """
      ## Scratch folder.
      self.dir = Path(tempfile.mkdtemp(prefix="capsule_plugins_"))

   def tearDown(self) -> None:
      """!Removes it.
      @return None
      """
      shutil.rmtree(self.dir, ignore_errors=True)

   def plugin(self, pid: str, files: dict[str, str], **manifest_keys: Any) -> Path:
      """!Writes a plugin folder.
      @param pid            plugin id
      @param files          {relative path: text}
      @param manifest_keys  plugin.json overrides
      @return its folder
      """
      folder = self.dir / pid
      data = {"schema": "capsule.plugin/1", "id": pid, "version": "2026.10.17.0690", "api": registry.API,
              "extension": {"module": "ext.extension"}}
      data.update(manifest_keys)
      folder.mkdir(parents=True)
      (folder / "plugin.json").write_text(json.dumps(data), encoding="utf-8")
      files = {"ext/__init__.py": "", **files}
      for rel, text in files.items():
         (folder / rel).parent.mkdir(parents=True, exist_ok=True)
         (folder / rel).write_text(textwrap.dedent(text), encoding="utf-8")
      return folder

   def test_versions(self) -> None:
      """!Zero-padded UTC calendar versions, requirements, the 6-month rule, deprecation warnings.
      @return None
      """
      self.assertEqual(versions.parse("2026.10.17.0690"), (2026, 10, 17, 690))
      for bad in ("2026.10.17.690", "2026.1.05.0000", "2026.02.30.0000", "2026.10.17.1440", 20261017):
         with self.assertRaises(versions.VersionError):
            versions.parse(bad)
      self.assertTrue(versions.satisfies("2026.10.17.0690", ">=2026.10.01.0000, <2027.01.01.0000"))
      self.assertFalse(versions.satisfies("2026.09.30.1439", ">=2026.10.01.0000"))
      self.assertEqual(versions.removable_from("2026.08.31.0100"), "2027.02.28")
      self.assertTrue(versions.may_remove("2026.04.17.0000", "2026.10.17.0000"))
      self.assertFalse(versions.may_remove("2026.04.18.0000", "2026.10.17.1439"))

      @versions.deprecated("2026.10.17.0000", "new_thing()")
      def old_thing() -> int:
         return 1
      with warnings.catch_warnings(record=True) as caught:
         warnings.simplefilter("always")
         self.assertEqual(old_thing(), 1)
      self.assertIn("removed from 2027.04.17", str(caught[0].message))

   def test_manifest_rules(self) -> None:
      """!Ids, versions, the cli key (built-ins only), connectors refused by the loader.
      @return None
      """
      good = {"schema": "capsule.plugin/1", "id": "acme.moods", "version": "2026.10.17.0690", "api": 1,
              "extension": {"module": "m.e"}}
      manifest.PluginInfo(self.dir, good)
      for change, needle in ((dict(id="Moods"), "reverse-domain"), (dict(version="2026.10.17.690"), "zero-padded"),
                             (dict(cli="moods"), "studio's own"), (dict(extension=None), "an extension, a connector"),
                             (dict(colour=1), "unknown key")):
         with self.assertRaises(manifest.ManifestError) as cm:
            manifest.PluginInfo(self.dir, {**good, **change})
         self.assertIn(needle, str(cm.exception))
      self.assertEqual(manifest.PluginInfo(self.dir, {**good, "cli": "moods"}, builtin=True).cli, "moods")

   def test_load_and_register(self) -> None:
      """!A plugin registers a tool, an overlay, hover text, a command and a validator; ids get its prefix.
      @return None
      """
      folder = self.plugin("acme.marks", {"ext/extension.py": """
            from capsule_studio.plugins import Diagnostic, MapOverlay, MapTool
            from . import helper

            class Mark(MapTool):
                id = "mark"
                label = "Mark"
                def apply(self, view, cells):
                    view.edit("Mark", lambda: helper.mark(view.doc, cells))

            class Dots(MapOverlay):
                id = "dots"
                title = "Dots"
                def prepare(self, view):
                    return lambda x, y, cell: ((1, 2, 3, 4), ".")

            def register(ctx):
                ctx.add_map_tool(Mark())
                ctx.add_map_overlay(Dots())
                ctx.add_hover_text(lambda view, x, y, cell: f"at {x},{y}")
                ctx.add_command("hello", "says hello", lambda q: q.add_argument("who"), lambda a: print("hi", a.who))
                ctx.add_validator(lambda project, map_name: [Diagnostic("warning", "careful", map_name)])
            """, "ext/helper.py": """
            from capsule_studio.core import maps

            def mark(doc, cells):
                for x, y in cells:
                    maps.set_attributes(doc, x, y, env=9)
            """})
      reg = registry.Registry()
      self.assertEqual(loader.load_folders(reg, [folder]), ["acme.marks"])
      self.assertEqual([t.id for t in reg.map_tools()], ["acme.marks/mark"])
      self.assertEqual(reg.map_overlays()[0].prepare(None)(0, 0, 0), ((1, 2, 3, 4), "."))
      self.assertEqual(reg.hover_texts()[0](None, 1, 2, None), "at 1,2")
      self.assertEqual([(c.group, c.name) for c in reg.commands()], [("acme.marks", "hello")])
      found = reg.validate(None, "m")
      self.assertEqual((found[0].message, found[0].map, found[0].plugin), ("careful", "m", "acme.marks"))
      reg.forget(["acme.marks"])
      self.assertEqual(reg.map_tools(), [])
      self.assertEqual(loader.load_folders(reg, [folder]), ["acme.marks"])   # loads again after forget

   def test_two_plugins_same_package_name(self) -> None:
      """!Plugin packages are private per plugin.
      @return None
      """
      a = self.plugin("acme.a", {"ext/extension.py": "VALUE = 'a'\ndef register(ctx):\n    ctx.add_hover_text("
                                                     "lambda *a: VALUE)\n"})
      b = self.plugin("acme.b", {"ext/extension.py": "VALUE = 'b'\ndef register(ctx):\n    ctx.add_hover_text("
                                                     "lambda *a: VALUE)\n"})
      reg = registry.Registry()
      loader.load_folders(reg, [a, b])
      self.assertEqual([h(None, 0, 0, 0) for h in reg.hover_texts()], ["a", "b"])

   def test_refusals(self) -> None:
      """!Native files, platform wheels, ctypes, other API numbers, newer studio, missing dependencies,
      connectors and broken register() are refused, naming the plugin and file; nothing stays registered.
      @return None
      """
      cases = [
         (self.plugin("acme.native", {"ext/extension.py": "def register(ctx): pass\n", "ext/fast.so": "x"}),
          "ext/fast.so is a native binary"),
         (self.plugin("acme.wheel", {"ext/extension.py": "def register(ctx): pass\n",
                                     "wheels/np-1.0-cp312-cp312-linux_x86_64.whl": "x"}),
          "not a py3-none-any wheel"),
         (self.plugin("acme.ctypes", {"ext/extension.py": "import ctypes\ndef register(ctx): pass\n"}),
          "ext/extension.py:1 imports ctypes"),
         (self.plugin("acme.dyn", {"ext/extension.py": "import importlib\nimportlib.import_module('cffi')\n"}),
          "imports cffi"),
         (self.plugin("acme.api", {"ext/extension.py": "def register(ctx): pass\n"}, api=99), "plugin API 99"),
         (self.plugin("acme.future", {"ext/extension.py": "def register(ctx): pass\n"},
                      requires={"capsule_studio": ">=2099.01.01.0000"}), "needs capsule-studio"),
         (self.plugin("acme.deps", {"ext/extension.py": "def register(ctx): pass\n"},
                      requires={"plugins": ["acme.base"]}), "needs plugin(s) acme.base"),
         (self.plugin("acme.conn", {"ext/extension.py": "def register(ctx): pass\n"},
                      connector={"module": "ext.connector"}), "connectors"),
         (self.plugin("acme.broken", {"ext/extension.py": """
                from capsule_studio.plugins import MapTool
                class T(MapTool):
                    id = "t"
                def register(ctx):
                    ctx.add_map_tool(T())
                    raise RuntimeError("boom")
                """}), "RuntimeError: boom"),
      ]
      for folder, needle in cases:
         reg = registry.Registry()
         self.assertEqual(loader.load_folders(reg, [folder]), [], needle)
         self.assertIn(needle, reg.errors[0][1])
         self.assertEqual(reg.map_tools(), [])
         self.assertEqual(reg.plugins, {})

   def test_import_guard(self) -> None:
      """!Code in a watched folder cannot import ctypes or compiled modules outside the standard library.
      @return None
      """
      folder = self.dir / "guarded"
      folder.mkdir()
      (folder / "probe.py").write_text("def go():\n    import ctypes\n", encoding="utf-8")
      purity.install()
      purity.GUARD.watch("acme.guarded", folder)
      sys.path.insert(0, str(folder))
      try:
         sys.modules.pop("ctypes", None)
         import probe
         with self.assertRaises(ImportError) as cm:
            probe.go()
         self.assertIn("plugin acme.guarded: probe.py imports ctypes", str(cm.exception))
         import ctypes  # noqa: F401  (outside plugin code: fine)
      finally:
         sys.path.remove(str(folder))
         purity.GUARD.roots.pop(folder.resolve(), None)
         sys.modules.pop("probe", None)

   def test_project_plugins(self) -> None:
      """!Only plugins a world's project lists load; opening another world drops them.
      @return None
      """
      game = self.dir / "game"
      (game / "reference").mkdir(parents=True)
      (game / "data").mkdir()
      (game / "data" / "world.json").write_text("{}", encoding="utf-8")
      self.plugin("acme.listed", {"ext/extension.py": "def register(ctx):\n    ctx.add_hover_text(lambda *a: 'x')\n"})
      shutil.move(str(self.dir / "acme.listed"), str(game / "plugins" / "listed"))
      (game / "reference" / "project.json").write_text(json.dumps({
         "schema": "capsule.project/1", "name": "game", "maps": "data/world.json", "plugins": ["plugins/listed"]}),
          encoding="utf-8")
      reg = registry.Registry()
      ids, path = loader.load_project_plugins(reg, game / "data" / "world.json")
      self.assertEqual((ids, path), (["acme.listed"], (game / "reference" / "project.json").resolve()))
      self.assertEqual(len(reg.hover_texts()), 1)
      other = self.dir / "elsewhere" / "world.json"
      other.parent.mkdir()
      other.write_text("{}", encoding="utf-8")
      self.assertEqual(loader.load_project_plugins(reg, other, ids), ([], None))
      self.assertEqual(reg.hover_texts(), [])

   def test_builtin_extensions(self) -> None:
      """!The studio's own extensions load cleanly through the same host.
      @return None
      """
      reg = loader.builtin_registry()
      self.assertEqual(reg.errors, [])
      self.assertIn("studio.encounters", reg.plugins)
      self.assertEqual([s.panel_id for s in reg.panels("encounter-editor")], ["encounters"])
      # The map editor shows one extension panel of its own (S3: override sets are map editing, D-30); each world
      # tool runs standalone and in the Studio.
      self.assertEqual([s.panel_id for s in reg.panels("map-editor")], ["overrides"])
      for host, panel in (("event-editor", "events"), ("object-editor", "objects"),
                          ("location-editor", "locations")):
         self.assertEqual([s.panel_id for s in reg.panels(host)], [panel])
      self.assertEqual([s.panel_id for s in reg.panels(registry.STUDIO_HOSTS)],
                       ["encounters", "events", "locations", "objects", "overrides"])
      self.assertIn("studio.encounters/area", [t.id for t in reg.map_tools()])
      self.assertIn("studio.encounters/slots", [o.id for o in reg.map_overlays()])


class ExtensionTests(EncounterWorld):
   """!The encounter extension: brush, overlay, hover text, validator, commands."""

   def ext(self) -> registry.Registry:
      """!The registry with the studio's extensions.
      @return Registry
      """
      return loader.builtin_registry()

   def test_brush_overlay_hover(self) -> None:
      """!The brush paints slots as one undo step; the overlay colours by slot and marks slots without tables.
      @return None
      """
      p = self.project
      reg = self.ext()
      brush = next(t for t in reg.map_tools() if t.id == "studio.encounters/area")
      overlay = next(o for o in reg.map_overlays() if o.id == "studio.encounters/slots")
      view = MapView(p, "showcase")
      doc = p.map("showcase")
      cells = enc.slot_cells(doc.data)[0][:3]
      brush.slot = 7
      brush.apply(view, cells)
      self.assertEqual(doc.undo_label(), "Encounters (slot 7)")
      self.assertEqual({maps.unpack(maps.get(doc.data, x, y))["slot"] for x, y in cells}, {7})
      cell = overlay.prepare(view)
      x, y = cells[0]
      color, text = cell(x, y, maps.get(doc.data, x, y))
      self.assertEqual((color, text), ((230, 40, 40, 150), "7"))   # slot 7 has no table yet
      x1, y1 = enc.slot_cells(doc.data)[1][0]
      color, text = cell(x1, y1, maps.get(doc.data, x1, y1))
      self.assertEqual(text, "1")
      self.assertNotEqual(color[:3], (230, 40, 40))
      self.assertEqual(cell(0, 0, None), (None, None))
      hover = reg.hover_texts()[0]
      self.assertIn("slot 1", hover(view, x1, y1, maps.get(doc.data, x1, y1)))
      found = [d for d in reg.validate(p, "showcase") if d.plugin == "studio.encounters"]
      self.assertTrue(any("slot 7" in d.message and d.level == "warning" for d in found), found)
      brush.on = False
      brush.apply(view, cells)
      self.assertFalse(any(maps.unpack(maps.get(doc.data, x, y))["encounter"] for x, y in cells))

   def test_commands(self) -> None:
      """!The command group does what the panel does, compiling before saving.
      @return None
      """
      w = self.dir / "world.json"
      steps = [
         ("show", w, "--when", "night"),
         ("condition-add", w, "rain"),
         ("method-add", w, "old lure", "--trigger", "script"),
         ("table-add", w, "cave", 0, "walk", "--rate", "1/12", "--label", "Cave"),
         ("entry-add", w, "--map", "cave", 0, "Clodbun", "8-10", "--weight", 3, "--modifiers", "rain x2"),
         ("entry-add", w, "--map", "cave", 0, "Duskowl", 9, "--requires", "night"),
         ("entry-set", w, "--map", "cave", 0, 1, "--levels", "9-11", "--requires", "-"),
         ("entry-move", w, "--map", "cave", 0, 1, "up"),
         ("table-add", w, "cave", 0, "old lure"),
         ("table-set", w, "--map", "cave", 1, "--rate", "1/2"),
         ("shared-add", w, "pond", "--rate", "1/3"),
         ("entry-add", w, "--shared", "pond", "Tidepup", "5-7"),
         ("link", w, "--map", "cave", 1, "pond"),
         ("condition-rename", w, "night", "dark"),
         ("method-rename", w, "walk", "grass"),
         ("area", w, "showcase", 3, 0, 0, 40, 40),
         ("check", w, "--map", "cave"),
      ]
      for s in steps:
         status, out = self.run_cli("encounters", *s)
         self.assertEqual(status, 0, f"{s}: {out}")
      q = self.reopen()
      ts = enc.tables(enc.map_doc(q, "cave"))
      self.assertEqual([e["species"] for e in ts[0]["entries"]], ["Duskowl", "Clodbun"])
      self.assertEqual(ts[0]["entries"][0]["levels"], [9, 11])
      self.assertEqual(ts[0]["method"], "grass")
      self.assertEqual((ts[1]["table"], ts[1].get("rate")), ("pond", None))
      self.assertEqual(enc.conditions(q), ["dark", "rain"])
      self.assertEqual(set(enc.slot_cells(q.map("showcase").data)), {3})
      status, out = self.run_cli("encounters", "entry-add", w, "--map", "cave", 0, "Nobody", 3)
      self.assertEqual(status, 1)
      self.assertIn("unknown species 'Nobody'", out)
      status, out = self.run_cli("encounters", "condition-remove", w, "dark")
      self.assertEqual(status, 1)
      self.assertIn("is used by", out)
      status, out = self.run_cli("encounters", "check", w)
      self.assertEqual(status, 0, out)
      self.assertIn("slot 3", out)   # the area painted slot 3, which has no table
      status, out = self.run_cli("world", "validate", w)
      self.assertEqual(status, 0, out)
      self.assertIn("[studio.encounters]", out)


if __name__ == "__main__":
   unittest.main()
