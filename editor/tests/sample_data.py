"""!Where the studio's tests get their battle data (S13, after the engine's E11).

The engine's neutral fixture is its Starter sample (samples/starter, E9): every test that is not about one
ruleset uses a copy of it. The Gen-3 sample moved to the reference repo (templates/gen3 of the reference rules,
E11; since D-37 the rules/ folder of CapsuleCreatures_PocketProject), found as core.templates finds it
(CAPSULE_REFERENCE, then the PocketProject checkouts in the workspace folder). The few Gen-3 tests are kept in
their own classes, decorated with
needs_gen3: they run when the reference repo is found and are skipped otherwise.

The map sandbox's world names the Starter by the engine's layout (apps/sandbox_map/data/world.json "battle" is
../../../samples/starter/battle.json), so copy_engine_apps() copies apps and the Starter in that layout.
"""
from __future__ import annotations

import json
import shutil
import sys
import unittest
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TypeVar

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capsule_studio.core import engine, templates  # noqa: E402
from capsule_studio.core.battle import BattleProject  # noqa: E402

## A decorated test class or function.
Decorated = TypeVar("Decorated")

## The engine's samples folder (relative to the engine checkout).
SAMPLES = "samples"
## The engine's apps folder.
APPS = "apps"
## The Starter sample's folder name.
STARTER = "starter"
## The engine app that plays the Starter (its reference/project.json is the model of a Starter game's).
STARTER_APP = "starter_battle"
## The reference repo's Gen-3 sample (templates/gen3) and its game (apps/sandbox_battle).
GEN3 = "gen3"
## The reference repo's Gen-3 sandbox app.
GEN3_APP = "sandbox_battle"
## A game's project manifest, relative to the game folder.
PROJECT_JSON = ("reference", "project.json")
## A game's data folder.
DATA = "data"
## The reference repo's Gen-3 record data set (compat/gen3/record, R3: unstored roles, species fields, bit
## operators, a low-first wide draw; the engine's E13a features), relative to the reference root.
GEN3_RECORD = ("compat", GEN3, "record")
## Why a Gen-3 test is skipped.
NO_REFERENCE = ("the reference rules (CAPSULE_REFERENCE or CapsuleCreatures_PocketProject*/rules in the workspace) "
                "are not found: Gen-3 tests skip")


def starter_data() -> Path:
   """!The engine's Starter sample (battle.json, structure.json, ruleset.json, effects/, assets.json).
   @return folder
   """
   return engine.root() / SAMPLES / STARTER


def reference_root() -> Path | None:
   """!The reference repo checkout the studio finds (core.templates.reference_root()).
   @return Path, or None
   """
   return templates.reference_root()


def gen3_data() -> Path | None:
   """!The reference repo's Gen-3 sample (templates/gen3), when the repo is found.
   @return folder, or None
   """
   ref = reference_root()
   folder = ref / templates.REFERENCE_TEMPLATES / GEN3 if ref is not None else None
   return folder if folder is not None and (folder / "battle.json").is_file() else None


def gen3_app() -> Path | None:
   """!The reference repo's Gen-3 sandbox game (apps/sandbox_battle: reference/project.json, data/).
   @return folder, or None
   """
   ref = reference_root()
   folder = ref / APPS / GEN3_APP if ref is not None else None
   return folder if folder is not None and folder.joinpath(*PROJECT_JSON).is_file() else None


def method1_source() -> Path | None:
   """!The reference repo's Method-1 generator (compat/gen3/src/random_method1.cpp).
   @return Path, or None
   """
   ref = reference_root()
   path = ref / "compat" / GEN3 / "src" / "random_method1.cpp" if ref is not None else None
   return path if path is not None and path.is_file() else None


def gen3_record_data() -> Path | None:
   """!The reference repo's Gen-3 record data set (compat/gen3/record), when the repo is found.
   @return folder, or None
   """
   ref = reference_root()
   folder = ref.joinpath(*GEN3_RECORD) if ref is not None else None
   return folder if folder is not None and (folder / "battle.json").is_file() else None


def needs_gen3_record(item: Decorated) -> Decorated:
   """!Skips a test (class or function) when the reference repo's Gen-3 record data set is not found.
   @param item  the test
   @return the decorated item
   """
   skip: Callable[[Decorated], Decorated] = unittest.skipUnless(gen3_record_data() is not None, NO_REFERENCE)
   return skip(item)


def make_gen3_record_game(root: Path) -> Path:
   """!The reference repo's Gen-3 record data set as a game folder (the Starter app's project.json naming it;
   needs_gen3_record tests only).
   @param root  the game folder
   @return the copied battle.json
   """
   data = gen3_record_data()
   assert data is not None, NO_REFERENCE
   return make_game(root, data)


def needs_gen3(item: Decorated) -> Decorated:
   """!Skips a Gen-3 test (class or method) when the reference repo is not found.
   @param item  test class or method
   @return the decorated item
   """
   skip: Callable[[Decorated], Decorated] = unittest.skipUnless(gen3_data() is not None, NO_REFERENCE)
   return skip(item)


def copy_battle_data(battle_json: Path, folder: Path) -> None:
   """!Copies battle data and every file it is built from (structure, ruleset, effects, sequences) into a folder.
   @param battle_json  the battle.json to copy
   @param folder       target folder (the same relative layout)
   @return None
   """
   base = battle_json.parent
   for f in BattleProject.open(battle_json).files():
      out = folder / f.relative_to(base)
      out.parent.mkdir(parents=True, exist_ok=True)
      shutil.copy(f, out)


def make_game(root: Path, data: Path | None = None, project: Path | None = None) -> Path:
   """!A game folder from sample data: reference/project.json (the sample app's, naming data/battle.json and
   data/assets.json) and data/ (the battle data, what it is built from, and its assets.json when it has one).
   @param root     the game folder
   @param data     the sample folder (default the Starter)
   @param project  the project manifest to start from (default the Starter app's)
   @return the copied battle.json
   """
   data = data if data is not None else starter_data()
   project = project if project is not None else engine.root().joinpath(APPS, STARTER_APP, *PROJECT_JSON)
   manifest = json.loads(project.read_text(encoding="utf-8"))
   manifest["battle"] = f"{DATA}/battle.json"
   copy_battle_data(data / "battle.json", root / DATA)
   if (data / "assets.json").is_file():
      shutil.copy(data / "assets.json", root / DATA / "assets.json")
      manifest["assets"] = f"{DATA}/assets.json"
   else:
      manifest.pop("assets", None)
   out = root.joinpath(*PROJECT_JSON)
   out.parent.mkdir(parents=True, exist_ok=True)
   out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
   return root / DATA / "battle.json"


def make_gen3_game(root: Path) -> Path:
   """!The reference repo's Gen-3 sandbox as a game folder (needs_gen3 tests only).
   @param root  the game folder
   @return the copied battle.json
   """
   app = gen3_app()
   assert app is not None, NO_REFERENCE
   return make_game(root, app / DATA, app.joinpath(*PROJECT_JSON))


def copy_engine_apps(root: Path, apps: Iterable[str], parts: Iterable[str] = (DATA,)) -> Path:
   """!Copies engine apps in the engine's layout with the Starter they name: root/apps/APP/PART and
   root/samples/starter (sandbox_map's world names ../../../samples/starter/battle.json).
   @param root   the temporary root
   @param apps   app names ("sandbox_map", "starter_battle")
   @param parts  sub-folders of each app to copy ("data", "reference")
   @return root/apps
   """
   src = engine.root() / APPS
   out = root / APPS
   for app in apps:
      for part in parts:
         if (src / app / part).is_dir():
            shutil.copytree(src / app / part, out / app / part)
   shutil.copytree(starter_data(), root / SAMPLES / STARTER)
   return out


## The engine's map test world (tests/data/maps: invented fixtures of every map rule; I2's fixed tileset and maps
## fixed_a / fixed_b, I3's map crowd), relative to the engine checkout.
ENGINE_MAPS = ("tests", "data", "maps")


def copy_engine_maps(root: Path) -> Path:
   """!Copies the engine's map test world in the engine's layout (its world names
   ../../../samples/starter/battle.json): root/tests/data/maps and root/samples/starter.
   @param root  the temporary root
   @return the copy's world.json
   """
   out = root.joinpath(*ENGINE_MAPS)
   shutil.copytree(engine.root().joinpath(*ENGINE_MAPS), out)
   shutil.copytree(starter_data(), root / SAMPLES / STARTER)
   return out / "world.json"


## Where make_field_game() puts the Starter in the game (beside data/, as the studio's new games lay it out).
FIELD_BATTLE = "battle"
## The map sandbox's files naming the battle data, relative to the game's data folder, and their path to it.
FIELD_BATTLE_NAMES = {("world.json",): f"../{FIELD_BATTLE}/battle.json",
                      ("scripts", "scripts.json"): f"../../{FIELD_BATTLE}/battle.json"}


def make_field_game(root: Path) -> Path:
   """!The map sandbox as one game folder (F2: the Starter's field actions, the world's object kinds, map tags and
   flight points, the scripts the actions run): root/data (sandbox_map's data), root/battle (the Starter) and
   root/reference/project.json naming them. The Starter sits inside the game, so the battle pages find the world
   and the scripts (codepage.find_project() from the battle data).
   @param root  the game folder
   @return the copied battle.json
   """
   app = engine.root() / APPS / "sandbox_map"
   shutil.copytree(app / DATA, root / DATA)
   copy_battle_data(starter_data() / "battle.json", root / FIELD_BATTLE)
   for parts, battle in FIELD_BATTLE_NAMES.items():
      path = root.joinpath(DATA, *parts)
      doc = json.loads(path.read_text(encoding="utf-8"))
      doc["battle"] = battle
      path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
   manifest = json.loads(app.joinpath(*PROJECT_JSON).read_text(encoding="utf-8"))
   manifest["battle"] = f"{FIELD_BATTLE}/battle.json"
   out = root.joinpath(*PROJECT_JSON)
   out.parent.mkdir(parents=True, exist_ok=True)
   out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
   return root / FIELD_BATTLE / "battle.json"
