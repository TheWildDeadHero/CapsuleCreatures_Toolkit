"""!Battle data templates (S10, D-23 section 3.5): discovery (built in, engine samples, reference repo,
plugins), reading template.json, applying with relative paths and editor.template, new games, the CLI, and each
template applied to a temporary game and compiled by the engine.

With CAPSULE_BENCH_BUILD=1 the Starter game's bench is built once (the engine's default generator) and the engine's
Starter bench scenarios (tests/bench/starter/*.json, "rng": "default") reproduce their golden transcripts in it.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import bench, engine, manifest_io, templates  # noqa: E402
from capsule_studio.core.battle import BattleProject  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.structure import resources, stats  # noqa: E402
from capsule_studio.plugins import loader, registry  # noqa: E402
from sample_data import gen3_data, needs_gen3  # noqa: E402

## Environment variable that enables the slow bench build test (test_bench.BUILD_ENV).
BUILD_ENV = "CAPSULE_BENCH_BUILD"


def run_cli(*argv: str) -> tuple[int, str]:
   """!Runs the CLI.
   @param argv  arguments
   @return (status, stdout + stderr)
   """
   out, err = io.StringIO(), io.StringIO()
   with redirect_stdout(out), redirect_stderr(err):
      status = cli(list(argv))
   return status, out.getvalue() + err.getvalue()


def write_template(folder: Path, tid: str = "mine", parts: dict[str, list[str]] | None = None,
                   files: dict[str, str] | None = None, **keys: object) -> Path:
   """!Writes a template folder.
   @param folder  the folder
   @param tid     its id
   @param parts   template.json parts (default: one structure file)
   @param files   {relative path: text} written beside it
   @param keys    other template.json keys (overrides)
   @return the folder
   """
   files = {"structure.json": "{}"} if files is None else files
   for rel, text in files.items():
      (folder / rel).parent.mkdir(parents=True, exist_ok=True)
      (folder / rel).write_text(text, encoding="utf-8")
   data = {"schema": templates.SCHEMA, "id": tid, "name": tid.capitalize(), "description": "test", "version": 1,
           "parts": parts if parts is not None else {"structure": ["structure.json"]}}
   data.update(keys)
   manifest_io.save(folder / templates.TEMPLATE_FILE, data)
   return folder


class TemplateTestCase(unittest.TestCase):
   """!Base: a temporary folder.

   @var dir
   The folder.
   """

   def setUp(self) -> None:
      """!Makes the folder.
      @return None
      """
      self.dir = Path(tempfile.mkdtemp(prefix="capsule_templates_"))

   def tearDown(self) -> None:
      """!Removes it.
      @return None
      """
      shutil.rmtree(self.dir, ignore_errors=True)


class DiscoveryTests(TemplateTestCase):
   """!Where templates come from and what template.json may say."""

   def test_builtin_and_engine(self) -> None:
      """!Blank is built in, Starter is the engine's sample (samples/starter/template.json), in that order.
      @return None
      """
      found, problems = templates.discover()
      self.assertEqual(problems, [])
      ids = [t.id for t in found]
      self.assertEqual(ids[:2], ["blank", "starter"])
      blank, starter = found[0], found[1]
      self.assertEqual((blank.origin, starter.origin), (templates.BUILTIN, templates.ENGINE))
      self.assertEqual(starter.folder, (engine.root() / "samples" / "starter").resolve())
      self.assertIn("effects/moves.ceffect", starter.parts["logic"])
      self.assertEqual(starter.files(["structure"]), ["structure.json"])
      self.assertEqual(templates.find("Starter").id, "starter")
      self.assertIn("engine sample", starter.label())
      with self.assertRaises(DocumentError):
         templates.find("nothing")
      with self.assertRaises(DocumentError):
         starter.files(["colour"])

   def test_manifest_rules(self) -> None:
      """!Schema, id, version, parts and their files are checked; paths stay inside the folder.
      @return None
      """
      good = write_template(self.dir / "good")
      self.assertEqual(templates.load(good, templates.BUILTIN).parts, {"structure": ("structure.json",)})
      bad = [(dict(schema="capsule.template/2"), "not a template"), (dict(id="Mine"), "lower-case"),
             (dict(version=0), "whole number"), (dict(parts={}), "parts maps"),
             (dict(parts={"art": ["structure.json"]}), "unknown part"),
             (dict(parts={"structure": ["../structure.json"]}), "plain relative path"),
             (dict(parts={"structure": ["/structure.json"]}), "plain relative path"),
             (dict(parts={"structure": ["gone.json"]}), "not in"),
             (dict(parts={"structure": ["structure.json"], "logic": ["structure.json"]}), "listed twice"),
             (dict(colour=1), "unknown key")]
      for i, (change, needle) in enumerate(bad):
         folder = write_template(self.dir / f"bad{i}", **change)
         with self.assertRaises(DocumentError, msg=change) as cm:
            templates.load(folder, templates.BUILTIN)
         self.assertIn(needle, str(cm.exception))

   def test_reference_repo(self) -> None:
      """!The reference repo (CAPSULE_REFERENCE) adds its templates/*/template.json; a repeated id is left out.
      @return None
      """
      ref = self.dir / "rules"
      write_template(ref / "templates" / "gen3", "gen3")   # the real repo's id (E11)
      write_template(ref / "templates" / "again", "starter")
      with mock.patch.dict(os.environ, {templates.REFERENCE_ENV: str(ref)}):
         self.assertEqual(templates.reference_root(), ref.resolve())
         found, problems = templates.discover()
      gen3 = next(t for t in found if t.id == "gen3")
      self.assertEqual((gen3.origin, gen3.folder), (templates.REFERENCE, (ref / "templates" / "gen3").resolve()))
      self.assertEqual([t.origin for t in found if t.id == "starter"], [templates.ENGINE])
      self.assertTrue(any("'starter'" in p and "left out" in p for p in problems))

   @needs_gen3
   def test_real_reference_repo(self) -> None:
      """!The reference repo's Gen-3 template (E11, skipped without the repo): found as "gen3", a game made from it
      compiles and records the template.
      @return None
      """
      gen3 = templates.find("gen3")
      self.assertEqual((gen3.origin, gen3.name), (templates.REFERENCE, "Gen-3 reference"))
      self.assertEqual(gen3.folder, gen3_data().resolve())
      project = templates.new_game(self.dir / "gen3_game", gen3)
      battle_json = project.parent.parent / json.loads(project.read_text(encoding="utf-8"))["battle"]
      p = BattleProject.open(battle_json)
      self.assertIsNone(p.validate())
      self.assertEqual(templates.recorded(battle_json), {"id": "gen3", "version": gen3.version})

   def plugin(self, pid: str, api: int, register: str) -> Path:
      """!Writes a plugin folder with a template folder "tpl".
      @param pid       plugin id
      @param api       plugin.json api
      @param register  the body of register(ctx)
      @return its folder
      """
      folder = self.dir / pid
      data = {"schema": "capsule.plugin/1", "id": pid, "version": "2026.10.17.0690", "api": api,
              "extension": {"module": "ext.extension"}}
      folder.mkdir(parents=True)
      (folder / "plugin.json").write_text(json.dumps(data), encoding="utf-8")
      (folder / "ext").mkdir()
      (folder / "ext" / "__init__.py").write_text("", encoding="utf-8")
      (folder / "ext" / "extension.py").write_text(textwrap.dedent(f"""
         def register(ctx):
            {register}
         """), encoding="utf-8")
      write_template(folder / "tpl", "plugged")
      return folder

   def test_plugin_templates(self) -> None:
      """!Plugin API 2: ctx.add_battle_template() adds a template; a bad one is refused when the plugin loads; a
      plugin written for API 1 still loads.
      @return None
      """
      self.assertEqual((registry.MIN_API, registry.API), (1, 2))
      reg = registry.Registry()
      loaded = loader.load_folders(reg, [self.plugin("acme.tpl", registry.API, 'ctx.add_battle_template("tpl")'),
                                         self.plugin("acme.old", registry.MIN_API, "pass"),
                                         self.plugin("acme.bad", registry.API, 'ctx.add_battle_template("none")')])
      self.assertEqual(loaded, ["acme.tpl", "acme.old"])
      self.assertTrue(any("acme.bad" in msg for _where, msg in reg.errors))
      found, problems = templates.discover(reg)
      plugged = next(t for t in found if t.id == "plugged")
      self.assertEqual((plugged.origin, plugged.plugin), (templates.PLUGIN, "acme.tpl"))
      self.assertEqual(problems, [])
      self.assertIn("plugin acme.tpl", plugged.label())


class ApplyTests(TemplateTestCase):
   """!Copying a template, new games, the CLI."""

   def test_apply_keeps_paths_and_records(self) -> None:
      """!Every file lands at its relative path (effects/ included); the JSON manifests record editor.template;
      nothing is overwritten; some parts only.
      @return None
      """
      starter = templates.find("starter")
      target = self.dir / "data"
      written = templates.apply(starter, target)
      self.assertEqual(sorted(p.relative_to(target).as_posix() for p in written), sorted(starter.files()))
      self.assertTrue((target / "effects" / "conditions.ceffect").is_file())
      for rel in ("battle.json", "structure.json", "ruleset.json", "assets.json"):
         self.assertEqual(templates.recorded(target / rel), {"id": "starter", "version": starter.version}, rel)
      self.assertEqual((target / "effects" / "moves.ceffect").read_bytes(),
                       (starter.folder / "effects" / "moves.ceffect").read_bytes())
      with self.assertRaises(DocumentError) as cm:
         templates.apply(starter, target)
      self.assertIn("overwrite", str(cm.exception))
      only = templates.apply(starter, self.dir / "logic_only", ["logic"])
      self.assertEqual(len(only), len(starter.parts["logic"]))
      self.assertEqual(set(templates.game_manifests(written)), {"battle", "assets"})

   def test_new_game(self) -> None:
      """!new_game(): data/ + reference/project.json naming battle and assets by relative path; a non-empty folder
      is refused.
      @return None
      """
      game = self.dir / "Quest"
      project = templates.new_game(game, templates.find("starter"), "My quest")
      data = manifest_io.load(project)
      self.assertEqual(project, game / "reference" / "project.json")
      self.assertEqual((data["schema"], data["name"]), ("capsule.project/1", "My quest"))
      self.assertEqual((data["battle"], data["assets"]), ("data/battle.json", "data/assets.json"))
      self.assertEqual(data["editor"]["template"], {"id": "starter", "version": 1})
      blank = templates.new_game(self.dir / "Empty", templates.find("blank"))
      self.assertNotIn("assets", manifest_io.load(blank))
      self.assertEqual(manifest_io.load(blank)["name"], "Empty")
      with self.assertRaises(DocumentError):
         templates.new_game(game, templates.find("blank"))

   def test_cli(self) -> None:
      """!`new GAME --template`, `template list|show|apply|recorded`, `battle FILE new --template`.
      @return None
      """
      status, out = run_cli("template", "list")
      self.assertEqual(status, 0, out)
      self.assertIn("blank: Blank (built in, version 1)", out)
      self.assertIn("starter: Starter (engine sample, version 1)", out)
      status, out = run_cli("template", "show", "starter")
      self.assertEqual(status, 0, out)
      self.assertIn("logic: ruleset.json, effects/moves.ceffect", out)
      for tid in ("starter", "blank"):
         status, out = run_cli("new", str(self.dir / tid), "--template", tid)
         self.assertEqual(status, 0, out)
         status, out = run_cli("battle", str(self.dir / tid / "data" / "battle.json"), "validate")
         self.assertEqual(status, 0, out)
      status, out = run_cli("template", "recorded", str(self.dir / "blank" / "data" / "structure.json"))
      self.assertEqual((status, out.strip()), (0, "blank version 1"))
      status, out = run_cli("new", str(self.dir / "starter"), "--template", "starter")
      self.assertEqual(status, 1)
      self.assertIn("not an empty folder", out)
      status, out = run_cli("template", "apply", "starter", str(self.dir / "parts"), "--part", "structure")
      self.assertEqual(status, 0, out)
      self.assertEqual([p.name for p in (self.dir / "parts").iterdir()], ["structure.json"])
      status, out = run_cli("battle", str(self.dir / "copy" / "battle.json"), "new", "--template", "blank")
      self.assertEqual(status, 0, out)
      self.assertEqual(BattleProject.open(self.dir / "copy" / "battle.json").validate(), None)
      status, out = run_cli("battle", str(self.dir / "other" / "fight.json"), "new", "--template", "blank")
      self.assertEqual(status, 1)
      self.assertIn("has no fight.json", out)


class CompileTests(TemplateTestCase):
   """!Each template applied to a temporary game compiles with the engine."""

   def test_every_template_compiles(self) -> None:
      """!Every template found makes a game whose battle data compiles for each platform and whose assets
      compile.
      @return None
      """
      found, _problems = templates.discover()
      self.assertGreaterEqual(len(found), 2)
      for t in found:
         project = templates.new_game(self.dir / t.id, t)
         files = manifest_io.load(project)
         p = BattleProject.open(project.parent.parent / files["battle"])
         for platform in stats.platforms():
            self.assertIsNone(p.validate(platform), f"{t.id} on {platform}")
         if "assets" in files:
            status, out = run_cli("validate", str(project.parent.parent / files["assets"]))
            self.assertEqual(status, 0, out)

   def test_blank_is_neutral(self) -> None:
      """!Blank states the keys the engine requires (party_size, move_slots, learn.default_moves,
      exp_policy.share, the hit point resource), has no move resource, condition record, logic or game words.
      @return None
      """
      t = templates.find("blank")
      templates.apply(t, self.dir)
      p = BattleProject.open(self.dir / "battle.json")
      st = p.structure.data
      self.assertEqual(sorted(st["monster_layout"]), ["move_slots", "party_size", "roles"])
      self.assertIn("default_moves", st["learn"])
      self.assertIn("share", st["exp_policy"])
      rows = resources.resource_rows(p.structure)
      self.assertEqual([(r["name"], r["scope"], r["empty"]) for r in rows], [("hp", "battler", "faint")])
      for key in ("statuses", "volatiles", "weathers", "side_conditions", "field_conditions", "move_flags"):
         self.assertEqual(st[key], [], key)
      self.assertEqual(st["terms"], {})
      self.assertEqual(p.battle.data.get("effects", []), [])
      words = json.dumps([p.battle.data, st, p.ruleset.data]).lower()
      for word in ("pokemon", "pokémon", "trainer", "nature", "ability", "pp", "spa", "spd", "surf"):
         self.assertNotIn(f'"{word}"', words, word)

   def test_starter_in_the_studio(self) -> None:
      """!The Starter game: three battler resources with their persist roles and the EP regen formula, Strike's
      free cost, 8 move slots, 2 passive slots per species, the odds stat, the effect_odds pipeline.
      @return None
      """
      templates.new_game(self.dir / "s", templates.find("starter"))
      p = BattleProject.open(self.dir / "s" / "data" / "battle.json")
      rows = resources.resource_rows(p.structure)
      self.assertEqual([(r["name"], r["persist"], r["regen"]) for r in rows],
                       [("hp", "current_hp", None), ("mp", "current_mp", None), ("ep", "current_ep", "ep_regen")])
      self.assertEqual({r["amount"] for r in resources.cost_rows(p.battle, "Strike")}, {0})
      self.assertEqual(p.structure.data["monster_layout"]["move_slots"], 8)
      # two rolled slots; B2: the Sproutle line fills the hidden third slot (Nurture)
      self.assertTrue(all(len(sp["passives"]) in (2, 3) for sp in p.battle.data["species"]))
      self.assertEqual([r["name"] for r in stats.stat_list(p.structure) if r["odds"]], ["intelligence"])


@unittest.skipUnless(os.environ.get(BUILD_ENV) == "1", f"set {BUILD_ENV}=1 to build and run the real bench")
class StarterBenchTests(unittest.TestCase):
   """!The Starter game's bench, built once (slow)."""

   def test_starter_scenarios(self) -> None:
      """!The engine's Starter scenarios (rng "default") reproduce their golden transcripts in a new game.
      @return None
      """
      root = Path(tempfile.mkdtemp(prefix="capsule_starter_bench_"))
      try:
         templates.new_game(root / "game", templates.find("starter"))
         p = BattleProject.open(root / "game" / "data" / "battle.json")
         exe = bench.build(p, bench.DEFAULT_RNG)
         self.assertTrue(exe.is_file())
         sources = sorted((engine.root() / "tests" / "bench" / "starter").glob("*.json"))
         self.assertGreater(len(sources), 0)
         for src in sources:
            data = json.loads(src.read_text(encoding="utf-8"))
            expected = (src.parent / data.pop("expect")).read_text(encoding="utf-8")
            self.assertEqual(bench.scenario_rng(data), bench.DEFAULT_RNG, src.name)
            out = root / "game" / "data" / "bench" / src.name
            out.parent.mkdir(exist_ok=True)
            out.write_text(json.dumps(data), encoding="utf-8")
            run = bench.run(p, bench.open_scenario(out), None)
            self.assertTrue(run.ok(), f"{src.name}: {run.errors()}")
            self.assertEqual(run.transcript(), expected, src.name)
      finally:
         shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
   unittest.main()
