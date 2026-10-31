"""!Importing maps and tilesets from another world into the open one, with
what they need: the tilesets the maps draw from, the tilesets' sheet images,
the world behaviors (and vehicle classes) the maps' cells use, the map tags
and object kinds the maps name (F2), and the maps'
encounter tables (D-12) with the methods and conditions they name.

Both worlds use the same manifest formats (capsule.world/1,
capsule.tileset/2, capsule.map/2); other formats are a job for a converter.

Names that clash are handled like this:
  - a tileset identical to one the world already has (same content, same
    sheet pixels) is reused instead of copied;
  - otherwise a clashing tileset or map gets a new name (name_2, ...), and
    the imported maps' references follow it;
  - a behavior the world already has keeps the world's definition (a
    different one in the source is reported);
  - world-level settings (start, elevation levels) are not imported (a note
    says when the levels differ, compared as the engine resolves them);
  - encounters: each imported map's encounter file comes along (as
    encounters/NEW.json), with shared tables it uses copied into its own
    tables; methods and conditions the world lacks are added (a method the
    world has keeps the world's definition); when the world names no battle
    data, it takes the source's (species must exist there);
  - an imported map goes into a map group of the same path as in the source
    (created when missing), so the source's organisation comes along;
  - map events (B-3): warps between imported maps follow their new names
    and numbers; warps to maps not imported, events naming scripts, flags or
    variables this world's scripts manifest lacks, and area roots not
    imported are left out (and reported);
  - S3: override sets (D-30) come along; sets persisting through flags or
    variables this world's scripts manifest lacks are left out (and
    reported), a set name another map of the world has gets a number;
  - map objects (B-21) come along; objects naming scripts, flags or
    variables this world's scripts manifest lacks (in their pages and
    routes too) are left out (and reported); old "overrides" become pages
    (D-17: an override {flag, ...} is a page {"when": {flag}, ...}, in
    reverse order, since the last page that holds applies);
  - locations (D-17): the locations imported maps name come along with the
    banner styles they use (the world's definitions win; frames and
    preview sequences stay where they are, referred to from this world).

Nothing depends on a user interface. Imported documents are new and unsaved
(save_all() writes them); the world's additions are one undo step.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import field_rules, mapgroups, maps, paths
from .document import Document, DocumentError

if TYPE_CHECKING:
   from .world import Project

## Most behaviors a world may have.
MAX_WORLD_BEHAVIORS = 256
## Number a clashing name gets first ("name_2"; the unnumbered name counts as the first).
FIRST_COPY_NUMBER = 2
## Start position x, in metatiles, when the map has no painted passable cell (see _free_cell()).
FALLBACK_START_X = 3
## Start position y, in metatiles, when the map has no painted passable cell.
FALLBACK_START_Y = 3
## The attribute cell field of the collision (core.maps.cell_fields(): the engine's).
COLLISION_FIELD = "collision"

## A parsed JSON object (a manifest, a table, an event record).
JsonDict = dict[str, Any]


class ImportRefused(DocumentError):
   """!The import cannot be done; the message says why."""
   pass


def _image_digest(doc: Document, rel: str) -> str | None:
   """!Pixel digest of a sheet image (for comparing tilesets).
   @param doc  tileset Document
   @param rel  image path in the manifest
   @return hex digest, or None when unreadable
   """
   img = doc.image(rel)
   if img is None:
      return None
   w, h, px = img
   # The size goes in too, so images with the same bytes but another shape differ.
   return hashlib.sha1(f"{w}x{h}".encode() + bytes(px)).hexdigest()


def _tileset_key(doc: Document) -> str:
   """!What makes two tilesets the same: their content without the id, sheet
   images as pixel digests.
   @param doc  tileset Document
   @return comparable string
   """
   data = copy.deepcopy(doc.data)
   data.pop("id", None)
   data.pop("editor", None)
   for s in data.get("sheets", []):
      if "image" in s:
         s["image"] = _image_digest(doc, s["image"])
   return json.dumps(data, sort_keys=True)


def _free_name(name: str, taken: set[str], project: Project, kind: str) -> str:
   """!A name not used by the world (nor by a file in the default place).
   @param name     wanted name
   @param taken    names already used or planned
   @param project  target Project
   @param kind     "tilesets" or "maps"
   @return the name
   """
   out, n = name, FIRST_COPY_NUMBER
   while out in taken or (project.base / f"{kind}/{out}.json").exists():
      out = f"{name}_{n}"
      n += 1
   return out


def plan(project: Project, source: Project, map_names: Sequence[str] = (),
         tileset_names: Sequence[str] = ()) -> dict[str, Any]:
   """!Works out what an import would do, without changing anything.
   @param project        target Project
   @param source         source Project
   @param map_names      maps of the source to import
   @param tileset_names  tilesets of the source to import (the chosen maps' tilesets come along)
   @return dict with "maps" {source name: target name}, "tilesets" {source name: (target name, reused)},
           "behaviors" [names to add], "classes" [vehicle classes to add], "names" {map_tags / object_kinds key:
           names to add} (F2), "notes" [lines]
   """
   if Path(source.world.path).resolve() == Path(project.world.path).resolve():
      raise ImportRefused("that is the world already open")
   unknown = [m for m in map_names if m not in source.map_names()] + \
       [t for t in tileset_names if t not in source.tileset_names()]
   if unknown:
      raise ImportRefused(f"the source world has no map or tileset {unknown[0]!r}")
   # Tilesets to bring, in order without repeats: those asked for, then those the maps draw from.
   need = list(dict.fromkeys(tileset_names))
   src_behaviors = source.behavior_names()
   used_behaviors = []
   for m in map_names:
      data = source.map(m).data
      for t in maps.tilesets_of(data, source.tileset_names()):
         if t not in need:
            need.append(t)
      # Metatiles are "tileset/metatile".
      for n in data.get("metatiles", []):
         t = n.split("/", 1)[0]
         if t not in need and t in source.tileset_names():
            need.append(t)
      for b in maps.behaviors_of(data, src_behaviors):
         if b not in used_behaviors:
            used_behaviors.append(b)
   notes = []
   taken_ts = set(project.tileset_names())
   ts_plan = {}
   for t in need:
      if t in project.tileset_names():
         same = _tileset_key(project.tileset(t)) == _tileset_key(source.tileset(t))
         if same:
            ts_plan[t] = (t, True)
            notes.append(f"tileset {t}: the world already has the same one; reused")
            continue
         new = _free_name(t, taken_ts, project, "tilesets")
         notes.append(f"tileset {t}: the world has a different {t!r}; imported as {new!r}")
      else:
         new = _free_name(t, taken_ts, project, "tilesets")
      taken_ts.add(new)
      ts_plan[t] = (new, False)
   taken_maps = set(project.map_names())
   map_plan = {}
   for m in map_names:
      new = _free_name(m, taken_maps, project, "maps")
      if new != m:
         notes.append(f"map {m}: the world already has a map {m!r}; imported as {new!r}")
      taken_maps.add(new)
      map_plan[m] = new
   defs = {b.get("name"): b for b in source.world.data.get("behaviors", []) if isinstance(b, dict)}
   mine = {b.get("name"): b for b in project.world.data.get("behaviors", []) if isinstance(b, dict)}
   add_behaviors, add_classes = [], []
   classes = field_rules.mode_names(project.world)   # entries may be names or {"name", "speeds", ...} (E8)
   for b in used_behaviors:
      if b in mine:
         if defs.get(b, {"name": b}) != mine[b]:
            notes.append(f"behavior {b}: kept this world's definition (the source's differs)")
         continue
      add_behaviors.append(b)
      for c in defs.get(b, {}).get("passable", []) or []:
         if c not in classes and c not in add_classes:
            add_classes.append(c)
   most = field_rules.max_modes()
   if len(classes) + len(add_classes) > most:
      raise ImportRefused(f"the world would need {len(classes) + len(add_classes)} vehicle classes; "
                          f"at most {most}")
   if len(project.behavior_names()) + len(add_behaviors) > MAX_WORLD_BEHAVIORS:
      raise ImportRefused(f"the world would have more than {MAX_WORLD_BEHAVIORS} behaviors")
   # the levels as the engine resolves them (meets, on arrive, priority): either world may use the default rule,
   # the older elevation_priority list or its own 16 levels (E8)
   # F2: the map tags and object kinds the maps name, added to the world when it lacks them
   from . import map_field
   add_names: dict[str, list[str]] = {map_field.TAGS_KEY: [], map_field.KINDS_KEY: []}
   have = {map_field.TAGS_KEY: map_field.map_tags(project.world),
           map_field.KINDS_KEY: map_field.object_kinds(project.world)}
   for m in map_names:
      data = source.map(m).data
      named = {map_field.TAGS_KEY: [t for t in data.get(map_field.MAP_TAGS_KEY) or [] if isinstance(t, str)],
               map_field.KINDS_KEY: [o.get(map_field.OBJECT_KIND_KEY) for o in data.get("objects") or []
                                     if isinstance(o, dict) and isinstance(o.get(map_field.OBJECT_KIND_KEY), str)]}
      for key, names in named.items():
         for n in names:
            if n not in have[key] and n not in add_names[key]:
               add_names[key].append(n)
   if map_names and _levels(source.world) != _levels(project.world):
      notes.append("elevation levels differ between the worlds (meets, on arrive or priority); this world's are "
                   "kept")
   return {"maps": map_plan, "tilesets": ts_plan, "behaviors": add_behaviors, "classes": add_classes,
           "names": add_names, "notes": notes}


def _levels(world: Document) -> list[tuple[int, int, int]] | None:
   """!A world's 16 levels as the engine resolves them.
   @param world  world Document
   @return (meet mask, flags, priority) per level, or None when they do not compile
   """
   try:
      return [(mask, flags, prio) for mask, flags, prio, _name in
              field_rules.compile_levels(world.data)]
   except Exception:   # ManifestError: the world's own validation reports it
      return None


def run(project: Project, source: Project, map_names: Sequence[str] = (),
        tileset_names: Sequence[str] = ()) -> list[str]:
   """!Imports maps and tilesets (see plan()). The world's additions are one
   undo step; the new tileset and map documents are unsaved.
   @param project        target Project
   @param source         source Project
   @param map_names      maps to import
   @param tileset_names  tilesets to import
   @return report lines
   """
   p = plan(project, source, map_names, tileset_names)
   rename = {t: new for t, (new, _reused) in p["tilesets"].items()}
   new_tilesets = {}
   for t, (new, reused) in p["tilesets"].items():
      if reused:
         continue
      src = source.tileset(t)
      data = copy.deepcopy(src.data)
      data["id"] = new
      # (sheet, file stem, image): the images go to the new document after it exists, under free names.
      images = []
      for s in data.get("sheets", []):
         if "image" in s:
            img = src.image(s["image"])
            if img is None:
               raise ImportRefused(f"tileset {t}: cannot read the sheet image {s['image']}")
            images.append((s, Path(s.pop("image")).stem, img))
      new_tilesets[new] = (data, images)
   new_maps = {}
   for m, new in p["maps"].items():
      data = copy.deepcopy(source.map(m).data)
      data["id"] = new
      # "tileset/metatile" names follow the renamed tilesets.
      data["metatiles"] = [f"{rename.get(n.split('/', 1)[0], n.split('/', 1)[0])}/{n.split('/', 1)[1]}"
                           for n in data.get("metatiles", [])]
      if isinstance(data.get("tilesets"), list):
         data["tilesets"] = [rename.get(t, t) for t in data["tilesets"]]
      if not data.get("behaviors"):   # the source's default dictionary is its behavior 0
         data["behaviors"] = [source.behavior_names()[0] if source.behavior_names() else "normal"]
      new_maps[new] = data
   defs = {b.get("name"): b for b in source.world.data.get("behaviors", []) if isinstance(b, dict)}
   with project.world.edit("Import"):
      w = project.world.data
      if p["classes"]:
         # a class keeps the source's definition (speeds, running, animations, passable)
         src_classes = {field_rules.mode_names(source.world)[i]: c
                        for i, c in enumerate(source.world.data.get("vehicle_classes") or [])}
         w["vehicle_classes"] = list(w.get("vehicle_classes") or field_rules.mode_names(project.world)) + \
            [copy.deepcopy(src_classes.get(c, c)) for c in p["classes"]]
      if p["behaviors"]:
         w.setdefault("behaviors", [{"name": "normal"}])
         w["behaviors"].extend(copy.deepcopy(defs.get(b, {"name": b})) for b in p["behaviors"])
      for key, names in p["names"].items():
         if names:
            w[key] = list(w.get(key) or []) + names
      for new in new_tilesets:
         w.setdefault("tilesets", {})[new] = f"tilesets/{new}.json"
      for new in new_maps:
         w.setdefault("maps", {})[new] = f"maps/{new}.json"
      for m, new in p["maps"].items():
         path = mapgroups.group_of(source.world.data, m)
         if path:
            # Creates each missing group along the path, top first.
            for k in range(1, len(path) + 1):
               if mapgroups.find(w, path[:k]) is None:
                  mapgroups.add_group(project.world, path[:k - 1], path[k - 1])
            mapgroups.move_map(project.world, new, path)
      if not isinstance(w.get("start"), dict) and new_maps:
         first = next(iter(new_maps))
         x, y = _free_cell(new_maps[first])
         w["start"] = {"map": first, "x": x, "y": y, "facing": "down"}
   for new, (data, images) in new_tilesets.items():
      doc = project.adopt("tilesets", new, data)
      for s, stem, img in images:
         rel = doc.unique_image_path("sheets", stem)
         doc.add_image(rel, img)
         s["image"] = rel
   enc_lines = _import_encounters(project, source, p["maps"], new_maps)
   enc_lines += _import_events(project, p["maps"], new_maps)
   from . import locations as loc
   enc_lines += loc.import_locations(project, source, new_maps)
   for new, data in new_maps.items():
      project.adopt("maps", new, data)
   lines = []
   for t, (new, reused) in p["tilesets"].items():
      if not reused:
         lines.append(f"tileset {t}" + (f" as {new}" if new != t else ""))
   for m, new in p["maps"].items():
      lines.append(f"map {m}" + (f" as {new}" if new != m else ""))
   if p["behaviors"]:
      lines.append("behaviors " + ", ".join(p["behaviors"]))
   if p["classes"]:
      lines.append("vehicle classes " + ", ".join(p["classes"]))
   for key, names in p["names"].items():
      if names:
         lines.append(f"{key.replace('_', ' ')} " + ", ".join(names))
   return ["imported: " + ("; ".join(lines) if lines else "nothing new")] + p["notes"] + enc_lines


def _import_encounters(project: Project, source: Project, map_plan: dict[str, str],
                       new_maps: dict[str, JsonDict]) -> list[str]:
   """!Brings the imported maps' encounter tables along (see the module
   docstring). Changes the world (one undo step, when needed) and points
   each new map at its new encounter file, created unsaved.
   @param project   target Project
   @param source    source Project
   @param map_plan  {source map: target map}
   @param new_maps  {target map: its manifest data (changed here)}
   @return report lines
   """
   from . import encounters as enc
   files, used_methods, used_conditions = {}, [], []
   for m, new in map_plan.items():
      new_maps[new].pop("encounters", None)
      doc = enc.map_doc(source, m)
      if doc is None:
         continue
      tables = []
      for t in enc.tables(doc):
         t = copy.deepcopy(t)
         if "table" in t:   # a shared table: its entries come along inline
            rate, entries = enc.resolved(source, t)
            t.pop("table")
            t["rate"] = copy.deepcopy(rate if rate is not None else enc.DEFAULT_RATE)
            t["entries"] = copy.deepcopy(entries)
         tables.append(t)
         if t.get("method") not in used_methods:
            used_methods.append(t.get("method"))
         for e in t.get("entries", []):
            for c in e.get("requires", []) + e.get("excludes", []) + [x.get("when") for x in e.get("modifiers", [])]:
               if c not in used_conditions:
                  used_conditions.append(c)
      files[new] = tables
   if not files:
      return []
   lines = []
   src_methods = {x.get("name"): x for x in enc.methods(source)}
   add_methods = [n for n in used_methods if n not in enc.method_names(project)]
   add_conditions = [c for c in used_conditions if c not in enc.conditions(project)]
   if len(enc.methods(project)) + len(add_methods) > enc.MAX_METHODS:
      raise ImportRefused(f"the world would have more than {enc.MAX_METHODS} encounter methods")
   if len(enc.conditions(project)) + len(add_conditions) > enc.MAX_CONDITIONS:
      raise ImportRefused(f"the world would have more than {enc.MAX_CONDITIONS} encounter conditions")
   battle = None
   if project.world.data.get("battle") is None and enc.battle_path(source) is not None:
      try:
         battle = paths.relative(enc.battle_path(source), project.base)
      except DocumentError:   # another drive (Windows): no relative path leads there, so the world names none
         lines.append("encounters: the source world's battle data is on another drive; this world names none")
   elif enc.battle_path(source) is not None and enc.battle_path(source) != enc.battle_path(project):
      lines.append("encounters: species are checked against this world's battle data (the source names other)")
   if add_methods or add_conditions or battle:
      with project.world.edit("Import encounters"):
         classes = field_rules.mode_names(project.world)
         for n in add_methods:
            d = src_methods.get(n, {"name": n, "trigger": "step"})
            vehicles = [v for v in d.get("vehicles", []) if v in classes] if d.get("vehicles") else None
            enc.add_method(project.world, n, d.get("trigger", "step"), vehicles or None)
         for c in add_conditions:
            enc.add_condition(project.world, c)
         if battle:
            enc.set_battle(project.world, battle)
   if add_methods:
      lines.append("encounter methods " + ", ".join(add_methods))
   if add_conditions:
      lines.append("encounter conditions " + ", ".join(add_conditions))
   if battle:
      lines.append(f"battle data {battle} (from the source world)")
   for new, tables in files.items():
      path = (project.base / enc.FOLDER / f"{new}.json").resolve()
      # Taken (on disk, or by an open document): try NEW_2.json, NEW_3.json, ...
      n = FIRST_COPY_NUMBER
      while path.exists() or path in {d.path for d in project.documents()}:
         path = (project.base / enc.FOLDER / f"{new}_{n}.json").resolve()
         n += 1
      # Stored relative to the map file, which goes to the default place (as run() lists it).
      map_path = (project.base / "maps" / f"{new}.json").resolve()
      new_maps[new]["encounters"] = enc._rel(map_path.parent, path)
      project.adopt_document(path, enc.SCHEMA, {"schema": enc.SCHEMA, "id": path.stem, "tables": tables})
   return ["encounters: tables of " + ", ".join(files) + "".join(f"; {x}" for x in lines)]


def _import_events(project: Project, map_plan: dict[str, str], new_maps: dict[str, JsonDict]) -> list[str]:
   """!Keeps the imported maps' events that still resolve in this world (see
   the module docstring), renaming and renumbering warps between them.
   @param project   target Project
   @param map_plan  {source map name: new name}
   @param new_maps  {new name: map data}, changed in place
   @return report lines
   """
   from . import events as ev
   lines = []
   names = ev.names(project)
   known = names if names["error"] is None else None
   for new, data in new_maps.items():
      if "area" in data:
         if data["area"] in map_plan:
            data["area"] = map_plan[data["area"]]
         else:
            lines.append(f"map {new}: its area {data['area']!r} was not imported; it is its own area now")
            del data["area"]
   # Warps: keep those landing on imported maps, then renumber (dropping one shifts the rest).
   def warps_of(data: JsonDict) -> list[JsonDict]:
      """!A map's warp list, or [] when malformed."""
      e = data.get("events")
      ws = e.get("warps") if isinstance(e, dict) else None
      return [w for w in ws if isinstance(w, dict)] if isinstance(ws, list) else []

   keep = {}
   for new, data in new_maps.items():
      keep[new] = [isinstance(w.get("to"), str) and w["to"] in map_plan for w in warps_of(data)]
   changed = True
   while changed:   # a warp landing on a dropped warp goes too
      changed = False
      for new, data in new_maps.items():
         for i, w in enumerate(warps_of(data)):
            if keep[new][i]:
               dest = map_plan[w["to"]]
               n = w.get("warp", 0)
               if not (isinstance(n, int) and 0 <= n < len(keep.get(dest, [])) and keep[dest][n]):
                  keep[new][i] = False
                  changed = True
   dropped = 0
   for new, data in new_maps.items():
      e = data.get("events")
      if not isinstance(e, dict):
         continue
      warps = warps_of(data)
      out = []
      for i, w in enumerate(warps):
         if not keep[new][i]:
            dropped += 1
            continue
         dest = map_plan[w["to"]]
         # The new number counts the kept warps before the old one.
         w = dict(w, to=dest, warp=sum(keep[dest][:w.get("warp", 0)]))
         out.append(w)
      e["warps"] = out
      # Triggers and signs stay when every name they give is in this world's scripts manifest:
      # (event key, names() list it must be in).
      for kind, need in (("triggers", (("script", "scripts"), ("var", "vars"))),
                         ("signs", (("script", "scripts"), ("flag", "flags")))):
         kept = []
         items = e.get(kind)
         for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
               dropped += 1
               continue
            if known is not None and all(item.get(k) is None
                                         or (isinstance(item.get(k), str) and item.get(k) in known[t])
                                         for k, t in need):
               kept.append(item)
            else:
               dropped += 1
         e[kind] = kept
      for kind in list(e):
         if not e[kind]:
            del e[kind]
      if not e:
         del data["events"]
   if dropped:
      why = names["error"] or "they name maps not imported, or scripts, flags or variables this world lacks"
      lines.append(f"events: {dropped} left out ({why})")
   from . import objects as obj
   gone = sum(obj.import_objects(data, known) for data in new_maps.values())
   if gone:
      why = names["error"] or "they name scripts, flags or variables this world lacks"
      lines.append(f"objects: {gone} left out ({why})")
   # S3 (D-30): override sets persisting through names this world's scripts lack are left out; clashing names
   from . import override_sets
   taken = set(override_sets.world_names(project))
   gone = 0
   for data in new_maps.values():
      dropped, renamed = override_sets.import_sets(data, known, taken)
      gone += dropped
      lines += renamed
   if gone:
      why = names["error"] or "they persist through flags or variables this world's scripts manifest lacks"
      lines.append(f"override sets: {gone} left out ({why})")
   return lines


def _free_cell(data: JsonDict) -> tuple[int, int]:
   """!A painted, passable cell of a map (where a new start can go).
   @param data  map manifest
   @return (x, y)
   """
   col_mask, col_shift = maps.cell_fields()[COLLISION_FIELD]
   for c in data.get("chunks", []):
      for y, row in enumerate(c.get("cells", [])):
         for x, v in enumerate(row):
            # Attribute cells pack their fields (core.maps.cell_fields()): passable cells have no collision.
            if v is not None and not (v >> col_shift) & col_mask:
               # Chunk position (in chunks) and cell (in metatiles) to map metatiles.
               return c["at"][0] * maps.CHUNK + x, c["at"][1] * maps.CHUNK + y
   return FALLBACK_START_X, FALLBACK_START_Y
