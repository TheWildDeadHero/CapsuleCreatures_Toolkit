"""!Locations (D-17): the named places maps belong to, their name banners
and location previews, and the world's default warp transition.

The engine's tools/location_compiler.py (through map_compiler.py) is the one
authority on what is valid: check() and diagnostics() run it on the open,
unsaved documents. This module adds what editors need: styles, locations and
preview entries by name and index, changes as one undo step each, renames
that follow every map naming a location, and paths stored relative to the
world file. Qt-free; the Locations panel and `capsule-studio locations` use
it.

World keys (see location_compiler.py for every rule):
  - "transition": the transition of warps that name none (default fade);
  - "banner_styles": {name: {frame (24x24 PNG), ink, shadow, fill, border,
    frames, slide}};
  - "locations": {key: {name (the banner's text), banner (a style),
    preview: {show: always | first, sequences: [{when, sequence}]}}}.
Map key: "location" (a key of the world's locations).

Functions that change the world Document must be called inside
project.world.edit() (the host's run_edit()); set_map_location() changes a
map Document (inside its edit()). rename_location() and remove_location()
may change several documents and make their own undo steps, so call them
outside one.
"""
from __future__ import annotations

import copy
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from . import engine, events
from .document import Document, DocumentError

if TYPE_CHECKING:
   from ..plugins.registry import Diagnostic
   from .world import Project

## Transitions (capsule::script::Transition order).
TRANSITIONS = events.TRANSITIONS
## A world's transition when it names none.
DEFAULT_TRANSITION = "fade"
## Keys a banner style may hold.
STYLE_FIELDS = ("frame", "ink", "shadow", "fill", "border", "frames", "slide")
## Banner style colors.
COLORS = ("ink", "shadow", "fill", "border")
## What a style without a key uses (location_compiler.DEFAULTS).
STYLE_DEFAULTS = {"ink": "#f8f8f8", "shadow": "#303030", "fill": "#284878", "border": "#f8f8f8", "frames": 120,
                  "slide": 8}
## When a preview shows: every time, or on the first visit only.
SHOWS = ("always", "first")
## Longest banner text.
MAX_NAME = 28
## Locations per world.
MAX_LOCATIONS = 255
## Banner styles per world.
MAX_STYLES = 254
## Preview sequences per location.
MAX_SEQUENCES = 8
## A "#rrggbb" color.
COLOR_RE = re.compile(r"#[0-9A-Fa-f]{6}")
## Longest a banner stays on screen, in frames (a u16; location_compiler.MAX_BANNER_FRAMES).
MAX_BANNER_FRAMES = 65535
## Largest banner slide speed (location_compiler.MAX_BANNER_SLIDE).
MAX_BANNER_SLIDE = 64

## A parsed JSON object (a style, a location, a preview entry, a manifest).
JsonDict = dict[str, Any]
## Encounter condition names of a preview entry: a list, or one name.
WhenNames = str | Sequence[str]


# -- reading ------------------------------------------------------------------------------------

def transition(project: Project) -> str:
   """!The world's default warp transition.
   @param project  Project
   @return a name of TRANSITIONS
   """
   t = project.world.data.get("transition")
   return t if isinstance(t, str) else DEFAULT_TRANSITION


def styles(project: Project) -> dict[str, JsonDict]:
   """!The world's banner styles.
   @param project  Project
   @return {name: style dict} (the world's own; do not change them outside edit())
   """
   raw = project.world.data.get("banner_styles")
   return raw if isinstance(raw, dict) else {}


def locations(project: Project) -> dict[str, JsonDict]:
   """!The world's locations.
   @param project  Project
   @return {key: location dict} (the world's own)
   """
   raw = project.world.data.get("locations")
   return raw if isinstance(raw, dict) else {}


def location(project: Project, key: str) -> JsonDict:
   """!One location.
   @param project  Project
   @param key      its key
   @return the location dict
   """
   loc = locations(project).get(key)
   if not isinstance(loc, dict):
      raise DocumentError(f"no location {key!r} (locations: {', '.join(locations(project)) or 'none'})")
   return loc


def sequences(project: Project, key: str) -> list[JsonDict]:
   """!A location's preview entries.
   @param project  Project
   @param key      location key
   @return list of {"when"?, "sequence"}
   """
   pv = location(project, key).get("preview")
   seqs = pv.get("sequences") if isinstance(pv, dict) else None
   return seqs if isinstance(seqs, list) else []


def map_location(doc: Document) -> str | None:
   """!A map's location.
   @param doc  map Document
   @return location key, or None
   """
   loc = doc.data.get("location")
   return loc if isinstance(loc, str) else None


def maps_of(project: Project, key: str) -> list[str]:
   """!The maps of a location.
   @param project  Project
   @param key      location key
   @return list of map names
   """
   # I2: map_head() reads unopened maps without opening their documents
   return [n for n in project.map_names() if project.map_head(n)["location"] == key]


def describe_style(st: Any) -> str:
   """!One line about a banner style.
   @param st  the style (any JSON value: a broken one reads "?")
   @return text
   """
   if not isinstance(st, dict):
      return "?"
   look = f"frame {st['frame']}" if "frame" in st else "plain box"
   colors = ", ".join(f"{k} {st.get(k, STYLE_DEFAULTS[k])}" for k in ("ink", "fill"))
   return f"{look}; {colors}; {st.get('frames', STYLE_DEFAULTS['frames'])} frames, slide " \
          f"{st.get('slide', STYLE_DEFAULTS['slide'])}"


def describe_entry(v: Any) -> str:
   """!One line about a preview entry.
   @param v  {"when"?, "sequence"} (any JSON value: a broken one reads "?")
   @return text
   """
   when = v.get("when") if isinstance(v, dict) else None
   if isinstance(when, str):
      when = [when]
   cond = f" when {' and '.join(when)}" if when else ""
   return f"{v.get('sequence', '?') if isinstance(v, dict) else '?'}{cond}"


def describe(loc: Any) -> str:
   """!One line about a location.
   @param loc  the location (any JSON value: a broken one reads "?")
   @return text
   """
   if not isinstance(loc, dict):
      return "?"
   parts = [repr(loc.get("name", "?"))]
   parts.append(f"banner {loc['banner']}" if "banner" in loc else "no banner")
   pv = loc.get("preview")
   if isinstance(pv, dict):
      n = len(pv.get("sequences") or [])
      parts.append(f"preview ({pv.get('show', 'always')}, {n} sequence(s))")
   return "; ".join(parts)


# -- checks -------------------------------------------------------------------------------------

def _key(key: Any, what: str) -> None:
   """!Checks a style or location key.
   @param key   candidate (any value; a non-empty str passes)
   @param what  "style" or "location"
   @return None
   """
   if not isinstance(key, str) or not key.strip():
      raise DocumentError(f"a {what} needs a key")


def _name(name: Any) -> str:
   """!Checks a banner text.
   @param name  candidate (any value; a non-empty str that fits passes)
   @return it
   """
   if not isinstance(name, str) or not name.strip():
      raise DocumentError("a location needs a name (the banner's text)")
   if len(name) > MAX_NAME:
      raise DocumentError(f"{name!r} is {len(name)} characters; a banner fits {MAX_NAME}")
   return name


def _rel(project: Project, path: str | Path) -> str:
   """!A path as stored in the world (relative to the world file, '/' separated).
   @param project  Project
   @param path     path (absolute, or relative to the world file)
   @return text
   """
   p = Path(path)
   if p.is_absolute():
      p = Path(os.path.relpath(p.resolve(), project.base.resolve()))
   return p.as_posix()


def _world(project: Project) -> JsonDict:
   """!The world's data (to change inside project.world.edit()).
   @param project  Project
   @return dict
   """
   return project.world.data


def _section(project: Project, key: str) -> JsonDict:
   """!A world section, created when missing.
   @param project  Project
   @param key      "banner_styles" or "locations"
   @return the live dict
   """
   w = _world(project)
   if not isinstance(w.get(key), dict):
      w[key] = {}
   return w[key]


def _drop_empty(project: Project, key: str) -> None:
   """!Removes an empty world section.
   @param project  Project
   @param key      "banner_styles" or "locations"
   @return None
   """
   w = _world(project)
   if key in w and not w[key]:
      del w[key]


# -- the world's transition ---------------------------------------------------------------------

def set_transition(project: Project, name: str | None) -> None:
   """!Sets the world's default warp transition (call inside project.world.edit()).
   @param project  Project
   @param name     a name of TRANSITIONS, or None for the default (fade)
   @return None
   """
   w = _world(project)
   if name is None:
      w.pop("transition", None)
      return
   if name not in TRANSITIONS:
      raise DocumentError(f"transition is one of {', '.join(TRANSITIONS)}")
   w["transition"] = name


# -- banner styles ------------------------------------------------------------------------------

def _set_style_fields(project: Project, st: JsonDict, fields: dict[str, Any]) -> None:
   """!Applies style fields (None removes one: the default applies).
   @param project  Project
   @param st       the style (changed in place)
   @param fields   {key of STYLE_FIELDS: value or None}
   @return None
   """
   bad = sorted(set(fields) - set(STYLE_FIELDS))
   if bad:
      raise DocumentError(f"a banner style has no field(s) {', '.join(bad)} (known: {', '.join(STYLE_FIELDS)})")
   for k, v in fields.items():
      if v is None:
         st.pop(k, None)
         continue
      if k in COLORS:
         if not isinstance(v, str) or not COLOR_RE.fullmatch(v):
            raise DocumentError(f"{k} is a #rrggbb color, got {v!r}")
         v = v.lower()
      elif k == "frames":
         # bool is an int subclass: refused explicitly here and below.
         if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= MAX_BANNER_FRAMES:
            raise DocumentError(f"frames (how long the banner stays) is 1-{MAX_BANNER_FRAMES}")
      elif k == "slide":
         if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= MAX_BANNER_SLIDE:
            raise DocumentError(f"slide (frames to slide in) is 1-{MAX_BANNER_SLIDE}")
      elif k == "frame":
         if not isinstance(v, (str, Path)) or not str(v):
            raise DocumentError("frame is a 24x24 PNG")
         v = _rel(project, v)
      st[k] = v


def add_style(project: Project, name: str, **fields: Any) -> None:
   """!Adds a banner style (call inside project.world.edit()).
   @param project  Project
   @param name     its name
   @param fields   its fields (see STYLE_FIELDS; the rest default)
   @return None
   """
   _key(name, "banner style")
   if name in styles(project):
      raise DocumentError(f"there is a banner style {name!r} already")
   if len(styles(project)) >= MAX_STYLES:
      raise DocumentError(f"a world has up to {MAX_STYLES} banner styles")
   st = {}
   _set_style_fields(project, st, fields)
   _section(project, "banner_styles")[name] = st


def set_style(project: Project, name: str, **fields: Any) -> None:
   """!Changes a banner style; None removes a field (call inside project.world.edit()).
   @param project  Project
   @param name     style name
   @param fields   fields to change
   @return None
   """
   st = styles(project).get(name)
   if not isinstance(st, dict):
      raise DocumentError(f"no banner style {name!r}")
   _set_style_fields(project, st, fields)


def rename_style(project: Project, old: str, new: str) -> None:
   """!Renames a banner style; the locations using it follow (call inside project.world.edit()).
   @param project  Project
   @param old      its name
   @param new      new name
   @return None
   """
   all_styles = styles(project)
   if old not in all_styles:
      raise DocumentError(f"no banner style {old!r}")
   _key(new, "banner style")
   if new in all_styles:
      raise DocumentError(f"there is a banner style {new!r} already")
   w = _world(project)
   # Rebuilt rather than popped and re-added, so the style keeps its place in the file.
   w["banner_styles"] = {(new if k == old else k): v for k, v in all_styles.items()}
   for loc in locations(project).values():
      if isinstance(loc, dict) and loc.get("banner") == old:
         loc["banner"] = new


def remove_style(project: Project, name: str) -> None:
   """!Removes a banner style (call inside project.world.edit()); refused while a location uses it.
   @param project  Project
   @param name     style name
   @return None
   """
   if name not in styles(project):
      raise DocumentError(f"no banner style {name!r}")
   users = [k for k, loc in locations(project).items() if isinstance(loc, dict) and loc.get("banner") == name]
   if users:
      raise DocumentError(f"banner style {name!r} is used by {', '.join(users)}; give them another first")
   del _world(project)["banner_styles"][name]
   _drop_empty(project, "banner_styles")


# -- locations ----------------------------------------------------------------------------------

def _banner(project: Project, banner: str) -> str:
   """!Checks a banner style name.
   @param project  Project
   @param banner   style name
   @return it
   """
   if banner not in styles(project):
      raise DocumentError(f"no banner style {banner!r} (styles: {', '.join(styles(project)) or 'none'})")
   return banner


def add_location(project: Project, key: str, name: str, banner: str | None = None) -> None:
   """!Adds a location (call inside project.world.edit()).
   @param project  Project
   @param key      its key (maps name it)
   @param name     the banner's text
   @param banner   banner style, or None for no banner
   @return None
   """
   _key(key, "location")
   if key in locations(project):
      raise DocumentError(f"there is a location {key!r} already")
   if len(locations(project)) >= MAX_LOCATIONS:
      raise DocumentError(f"a world has up to {MAX_LOCATIONS} locations")
   loc = {"name": _name(name)}
   if banner is not None:
      loc["banner"] = _banner(project, banner)
   _section(project, "locations")[key] = loc


def set_location(project: Project, key: str, name: str | None = None,
                 banner: str | Literal[False] | None = False) -> None:
   """!Changes a location's name or banner (call inside project.world.edit()).
   @param project  Project
   @param key      location key
   @param name     new banner text, or None to keep it
   @param banner   banner style, None for no banner, or False to keep it
   @return None
   """
   loc = location(project, key)
   if name is not None:
      loc["name"] = _name(name)
   if banner is None:
      loc.pop("banner", None)
   elif banner is not False:
      loc["banner"] = _banner(project, banner)


def rename_location(project: Project, old: str, new: str) -> None:
   """!Renames a location; every map naming it follows (one undo step per
   changed document; call it outside an edit()).
   @param project  Project
   @param old      its key
   @param new      new key
   @return None
   """
   all_locs = locations(project)
   if old not in all_locs:
      raise DocumentError(f"no location {old!r}")
   _key(new, "location")
   if new in all_locs:
      raise DocumentError(f"there is a location {new!r} already")
   users = maps_of(project, old)
   with project.world.edit("Rename location") as w:
      # Rebuilt so the location keeps its place in the file.
      w["locations"] = {(new if k == old else k): v for k, v in all_locs.items()}
   for n in users:
      with project.map(n).edit("Rename location") as data:
         data["location"] = new


def remove_location(project: Project, key: str) -> list[str]:
   """!Removes a location; the maps naming it get none (one undo step per
   changed document; call it outside an edit()).
   @param project  Project
   @param key      location key
   @return the maps that had it
   """
   location(project, key)   # refuses an unknown key
   users = maps_of(project, key)
   with project.world.edit("Remove location") as w:
      del w["locations"][key]
      if not w["locations"]:
         del w["locations"]
   for n in users:
      with project.map(n).edit("Remove location") as data:
         data.pop("location", None)
   return users


def set_map_location(project: Project, doc: Document, key: str | None) -> None:
   """!Puts a map in a location (call inside doc.edit()).
   @param project  Project
   @param doc      map Document
   @param key      location key, or None for none
   @return None
   """
   if key is None:
      doc.data.pop("location", None)
      return
   location(project, key)   # refuses an unknown key
   doc.data["location"] = key


# -- previews -----------------------------------------------------------------------------------

def _when(project: Project, when: WhenNames | None) -> list[str] | None:
   """!Checks a preview entry's conditions.
   @param project  Project
   @param when     list of encounter condition names (or one name)
   @return the value to store (a list), or None for none
   """
   if when is None or when == []:
      return None
   when = [when] if isinstance(when, str) else when
   if not isinstance(when, (list, tuple)):
      raise DocumentError("when is a list of encounter condition names")
   conds = project.world.data.get("encounter_conditions")
   conds = conds if isinstance(conds, list) else []
   # Conditions are names; an object with a "name" counts too.
   known = [c if isinstance(c, str) else c.get("name") for c in conds if isinstance(c, (str, dict))]
   bad = [c for c in when if c not in known]
   if bad:
      raise DocumentError(f"no encounter condition {bad[0]!r} (the world's: {', '.join(known) or 'none'})")
   return list(when)


def set_preview(project: Project, key: str, show: str | None) -> None:
   """!Sets when a location's preview shows, or removes it (call inside project.world.edit()).
   A new preview has no sequences until add_sequence().
   @param project  Project
   @param key      location key
   @param show     "always" or "first", or None to remove the preview
   @return None
   """
   loc = location(project, key)
   if show is None:
      loc.pop("preview", None)
      return
   if show not in SHOWS:
      raise DocumentError(f"a preview shows {' or '.join(SHOWS)}")
   pv = loc.get("preview") if isinstance(loc.get("preview"), dict) else {"sequences": []}
   # "always" is the default, so it is not written.
   if show == "always":
      pv.pop("show", None)
   else:
      pv["show"] = show
   loc["preview"] = pv


def add_sequence(project: Project, key: str, sequence: str | Path, when: WhenNames | None = None) -> int:
   """!Adds a preview sequence (call inside project.world.edit()); the
   location gets a preview when it had none. The last entry whose
   conditions all hold plays.
   @param project   Project
   @param key       location key
   @param sequence  capsule.sequence/1 file (absolute, or relative to the world file)
   @param when      encounter condition names, or None
   @return its index
   """
   loc = location(project, key)
   pv = loc.get("preview") if isinstance(loc.get("preview"), dict) else {}
   seqs = pv.get("sequences") if isinstance(pv.get("sequences"), list) else []
   if len(seqs) >= MAX_SEQUENCES:
      raise DocumentError(f"a preview has up to {MAX_SEQUENCES} sequences")
   if not sequence:
      raise DocumentError("a preview entry needs a sequence file")
   entry = {}
   w = _when(project, when)
   if w is not None:
      entry["when"] = w
   entry["sequence"] = _rel(project, sequence)
   seqs.append(entry)
   pv["sequences"] = seqs
   loc["preview"] = pv
   return len(seqs) - 1


def set_sequence(project: Project, key: str, index: int, sequence: str | Path | None = None,
                 when: WhenNames | Literal[False] | None = False) -> None:
   """!Changes a preview entry (call inside project.world.edit()).
   @param project   Project
   @param key       location key
   @param index     entry index
   @param sequence  new sequence file, or None to keep it
   @param when      condition names, None for none, or False to keep them
   @return None
   """
   seqs = sequences(project, key)
   if not 0 <= index < len(seqs):
      raise DocumentError(f"location {key!r} has no preview entry {index}")
   e = seqs[index]
   if sequence is not None:
      e["sequence"] = _rel(project, sequence)
   if when is not False:
      w = _when(project, when)
      if w is None:
         e.pop("when", None)
      else:
         e["when"] = w


def remove_sequence(project: Project, key: str, index: int) -> None:
   """!Removes a preview entry (call inside project.world.edit()); the
   preview goes with its last entry.
   @param project  Project
   @param key      location key
   @param index    entry index
   @return None
   """
   seqs = sequences(project, key)
   if not 0 <= index < len(seqs):
      raise DocumentError(f"location {key!r} has no preview entry {index}")
   del seqs[index]
   if not seqs:
      location(project, key).pop("preview", None)


# -- checking -----------------------------------------------------------------------------------

def check(project: Project) -> str | None:
   """!Compiles the world's locations with the engine's rules, on the open documents.
   @param project  Project
   @return error message, or None when they compile
   """
   lc = engine.tool("location_compiler")
   w = project.world.data
   conds = w.get("encounter_conditions") or []
   try:
      # I2: compile_locations() reads a map's "location" only, so unopened maps are not opened for it
      maps_raw = {n: {"location": loc} if (loc := project.map_head(n)["location"]) is not None else {}
                  for n in project.map_names()}
      # [] collects the files read (a depfile), unused here.
      lc.compile_locations(w, project.base, maps_raw, [],
                           [c if isinstance(c, str) else c.get("name") for c in conds])
   except lc.LocationError as e:
      return str(e)
   except Exception as e:   # broken manifests
      return f"locations: {e}"
   return None


def diagnostics(project: Project, name: str | None = None) -> list[Diagnostic]:
   """!Location problems: what the build would reject, locations no map is
   in, and (when the world has locations) maps in none.
   @param project  Project
   @param name     only this map, or None for all
   @return list of plugins.Diagnostic
   """
   from ..plugins.registry import Diagnostic
   out = []
   error = check(project)
   if error:
      out.append(Diagnostic("error", error, name))
   locs = locations(project)
   if name is None:
      used = {project.map_head(n)["location"] for n in project.map_names()}
      for key in locs:
         if key not in used:
            out.append(Diagnostic("info", f"location {key!r} has no maps"))
   if locs:
      for n in [name] if name else project.map_names():
         if project.map_head(n)["location"] is None:
            out.append(Diagnostic("info", f"map {n}: in no location (no banner or preview on entering it)", n))
   return out


# -- importing ----------------------------------------------------------------------------------

def import_locations(project: Project, source: Project, new_maps: dict[str, JsonDict]) -> list[str]:
   """!Brings the locations imported maps name (the importer calls this; one
   undo step on the world when anything is added). A location the world
   has keeps the world's definition; one it lacks is copied with the banner
   style it uses (a style the world has keeps the world's), frame and
   sequence paths pointing at the source's files, and the encounter
   conditions its previews name.
   @param project   target Project
   @param source    source Project
   @param new_maps  {new map name: its data} (a "location" the source lacks too is removed)
   @return report lines
   """
   have = locations(project)
   src_locs = locations(source)
   wanted = []
   dropped = []
   for new, data in new_maps.items():
      key = data.get("location")
      if key is None:
         continue
      if key in have:
         continue
      if not isinstance(src_locs.get(key), dict):
         dropped.append(new)
         del data["location"]
      elif key not in wanted:
         wanted.append(key)
   lines = []
   if dropped:
      lines.append(f"locations: maps {', '.join(dropped)} named a location the source lacks; they are in none")
   if not wanted:
      return lines
   if len(have) + len(wanted) > MAX_LOCATIONS:
      raise DocumentError(f"the world would have more than {MAX_LOCATIONS} locations")

   def moved(rel: str) -> str:
      """!A source path, relative to this world."""
      return _rel(project, (source.base / rel).resolve())

   add_styles, add_conditions = [], []
   conds = project.world.data.get("encounter_conditions") or []
   names = [c if isinstance(c, str) else c.get("name") for c in conds]
   copies = {}
   for key in wanted:
      loc = copy.deepcopy(src_locs[key])
      # A style the world lacks comes along; one the source lacks too is dropped.
      banner = loc.get("banner")
      if banner is not None and banner not in styles(project) and banner not in add_styles:
         if isinstance(styles(source).get(banner), dict):
            add_styles.append(banner)
         else:
            del loc["banner"]
      pv = loc.get("preview")
      for e in (pv.get("sequences") or []) if isinstance(pv, dict) else []:
         if isinstance(e, dict) and isinstance(e.get("sequence"), str):
            e["sequence"] = moved(e["sequence"])
         when = e.get("when") if isinstance(e, dict) else None
         for c in [when] if isinstance(when, str) else (when or []):
            if c not in names and c not in add_conditions:
               add_conditions.append(c)
      copies[key] = loc
   with project.world.edit("Import locations"):
      for s in add_styles:
         st = copy.deepcopy(styles(source)[s])
         if isinstance(st.get("frame"), str):
            st["frame"] = moved(st["frame"])
         _section(project, "banner_styles")[s] = st
      for c in add_conditions:
         project.world.data.setdefault("encounter_conditions", []).append(c)
      for key, loc in copies.items():
         _section(project, "locations")[key] = loc
   lines.append("locations " + ", ".join(wanted) + (f" (banner styles {', '.join(add_styles)})" if add_styles else "")
                + (f" (encounter conditions {', '.join(add_conditions)})" if add_conditions else ""))
   return lines
