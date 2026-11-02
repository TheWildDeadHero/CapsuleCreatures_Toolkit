"""!The move categories of battle data (§3.2 "Categories"): the battle
manifest's "categories" list.

    "categories": [{"name": "physical", "offense": "attack", "defense": "defence"},
                   {"name": "elemental", "offense": "magic", "defense": "protection"}, {"name": "status"}]

A category names the stats its damage uses (offense and defense: any stat
but the pool stat, both or neither; one without them deals no formula
damage). Effect code tests a move's category (`move_is(...)`) and
rules.self_hit names one. At most the engine's MAX_CATEGORIES
(battle_compiler re-exports it).

Where a damaging move's category comes from (modes()):
  - BY_MOVE: each move names its category (default: the first);
  - BY_TYPE: the structure's `category_by_type` names a damaging
    category for every type, and a damaging move takes its type's (it states
    none; a status move still names its non-damaging category):

    "category_by_type": {"Earth": "physical", "Fire": "elemental", ...}

The engine's compiler decides what is valid (compile_categories(),
is_damaging(), compile_category_by_type()); set_mode() switches between the
two (to BY_TYPE each type takes its moves' most common damaging category;
a damaging move of another one then takes its type's, and is counted; back
to BY_MOVE every move keeps its category), set_type_category() sets one
type's.

The hit types' categories (structure `hit_category_by_type`,
hit_key()): in BY_MOVE mode a structure may name a damaging category for
every type that a damaging move hits with when the ruleset's move_type point
changed its type (e.g. a move whose type is chosen when it is used: the category follows the hit
type). set_hit() turns the table on (each type its moves' most common
damaging category) or off, set_hit_category() sets one type's; in BY_TYPE
mode category_by_type gives them (the engine refuses both: set_mode() to
BY_TYPE drops the hit table).

Each editing helper is one change: call it inside one battle.edit(). A
rename follows the moves, rules.self_hit.category, category_by_type and the
effect logic (core.battle.rename_entry()); a category something names
cannot be removed.
"""
from __future__ import annotations

from typing import Any

from .. import battle, engine
from ..document import Document, DocumentError

## A parsed JSON object.
JsonDict = dict[str, Any]
## One category as category_rows() gives it.
CategoryRow = dict[str, Any]

## The battle manifest's category list (core.battle kind).
CATEGORIES_KEY = "categories"
## Where a move's category comes from: the move.
BY_MOVE = "move"
## Where a damaging move's category comes from: its type (the structure's category_by_type).
BY_TYPE = "type"
## The structure key of the by-type rule: {type name: damaging category name}.
BY_TYPE_KEY = battle.BY_TYPE_KEY
## The content list naming the types.
TYPES_KEY = "types"


def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


def max_categories() -> int:
   """!Most categories (the engine's MAX_CATEGORIES).
   @return count
   """
   return int(_bc().MAX_CATEGORIES)


def modes() -> list[str]:
   """!Where a move's category may come from in this engine (BY_TYPE when its structure keys have category_by_type).
   @return [BY_MOVE] or [BY_MOVE, BY_TYPE]
   """
   return [BY_MOVE] + ([BY_TYPE] if BY_TYPE_KEY in _bc().STRUCTURE_KEYS else [])


def _listed(doc: Document) -> list[JsonDict]:
   """!The categories for reading.
   @param doc  battle Document
   @return dict entries ([] when the manifest has none)
   """
   given = battle.data_of(doc, CATEGORIES_KEY).get(CATEGORIES_KEY)
   return [c for c in given if isinstance(c, dict)] if isinstance(given, list) else []


def damage_stats(doc: Document) -> list[str]:
   """!The stats a category may name: every stat but the pool stat.
   @param doc  battle Document
   @return names
   """
   stats = battle.data_of(doc, "stats").get("stats")
   return [st["name"] for st in stats if isinstance(st, dict) and isinstance(st.get("name"), str)
           and st.get("pool") is not True] if isinstance(stats, list) else []


def _moves(doc: Document) -> list[JsonDict]:
   """!The battle data's moves (content).
   @param doc  battle Document
   @return dict entries
   """
   given = battle.data_of(doc, "moves").get("moves")
   return [m for m in given if isinstance(m, dict)] if isinstance(given, list) else []


def _type_names(doc: Document) -> list[str]:
   """!The battle data's type names (content).
   @param doc  battle Document
   @return names in order
   """
   given = battle.data_of(doc, TYPES_KEY).get(TYPES_KEY)
   return [t["name"] for t in given if isinstance(t, dict) and isinstance(t.get("name"), str)] \
      if isinstance(given, list) else []


def by_type(doc: Document) -> JsonDict | None:
   """!The structure's category_by_type (live: change it only inside an edit()).
   @param doc  battle Document
   @return {type: category}, or None in BY_MOVE mode
   """
   given = battle.data_of(doc, BY_TYPE_KEY).get(BY_TYPE_KEY)
   return given if isinstance(given, dict) else None


def mode(doc: Document) -> str:
   """!Where the battle data's damaging moves take their category from.
   @param doc  battle Document
   @return BY_TYPE when the structure states category_by_type, else BY_MOVE
   """
   return BY_TYPE if by_type(doc) is not None else BY_MOVE


def damaging_categories(doc: Document) -> list[str]:
   """!The categories that deal formula damage, as the engine's compiler decides (compile_categories(),
   is_damaging()): the choices of category_by_type.
   @param doc  battle Document
   @return names in order
   @throws DocumentError when the compiler refuses the categories
   """
   bc = _bc()
   stats = battle.data_of(doc, "stats").get("stats")
   shape = [{"name": st.get("name"), "pool": st.get("pool") is True}
            for st in (stats if isinstance(stats, list) else []) if isinstance(st, dict)]
   rows = _listed(doc)
   try:
      compiled = bc.compile_categories(rows, shape, battle.STRUCTURE_FILE)
   except bc.ManifestError as e:
      raise DocumentError(str(e)) from None
   return [c["name"] for i, c in enumerate(rows) if bc.is_damaging(compiled, i)]


def category_of(doc: Document, move: JsonDict) -> str | None:
   """!A move's category as the engine compiles it: the one it names, else its type's (BY_TYPE), else the first.
   @param doc   battle Document
   @param move  a move entry
   @return category name, or None without categories
   """
   if "category" in move:
      return move["category"]
   rule = by_type(doc)
   if rule is not None and move.get("type") in rule:
      return rule[move["type"]]
   rows = _listed(doc)
   return rows[0].get("name") if rows else None


def category_rows(doc: Document) -> list[CategoryRow]:
   """!Every category with what uses it.
   @param doc  battle Document
   @return copies in index order: index, name, offense, defense (None for a non-damaging one), damaging,
           moves (how many moves take it: by name, by their type or as the first), self_hit, types (the types
           category_by_type gives it)
   """
   d = battle.merged(doc)   # moves are content, the rest structure
   moves = _moves(doc)
   rule = by_type(doc) or {}
   self_hit = (d.get("rules") or {}).get("self_hit") if isinstance(d.get("rules"), dict) else None
   out = []
   for i, c in enumerate(_listed(doc)):
      name = c.get("name")
      count = sum(1 for m in moves if category_of(doc, m) == name)
      out.append({"index": i, "name": name, "offense": c.get("offense"), "defense": c.get("defense"),
                  "damaging": "offense" in c, "moves": count,
                  "self_hit": isinstance(self_hit, dict) and self_hit.get("category") == name,
                  "types": [t for t, cat in rule.items() if cat == name]})
   return out


def type_rows(doc: Document) -> list[JsonDict]:
   """!The by-type rule per type (BY_TYPE mode; empty in BY_MOVE).
   @param doc  battle Document
   @return [{"type", "category" (None when the rule leaves it out), "moves" (its damaging moves)}] in type order
   """
   rule = by_type(doc)
   if rule is None:
      return []
   damaging = set(damaging_categories(doc))
   moves = _moves(doc)
   return [{"type": t, "category": rule.get(t),
            "moves": sum(1 for m in moves if m.get("type") == t and category_of(doc, m) in damaging)}
           for t in _type_names(doc)]


def check_by_type(doc: Document) -> None:
   """!Checks category_by_type with the engine's compile_category_by_type() (every type, damaging categories).
   @param doc  battle Document
   @return None
   @throws DocumentError naming what the compiler refuses
   """
   bc = _bc()
   rule = by_type(doc)
   if rule is None:
      return
   stats = battle.data_of(doc, "stats").get("stats")
   shape = [{"name": st.get("name"), "pool": st.get("pool") is True}
            for st in (stats if isinstance(stats, list) else []) if isinstance(st, dict)]
   rows = _listed(doc)
   types = battle.data_of(doc, TYPES_KEY).get(TYPES_KEY)
   try:
      compiled = bc.compile_categories(rows, shape, battle.STRUCTURE_FILE)
      bc.compile_category_by_type(rule, types if isinstance(types, list) else [], rows, compiled,
                                  battle.STRUCTURE_FILE)
   except bc.ManifestError as e:
      raise DocumentError(str(e)) from None


def _place_rule(doc: Document, rule: JsonDict, key: str = BY_TYPE_KEY) -> None:
   """!Writes category_by_type (or the hit types' table) into the structure manifest right after "categories".
   @param doc   battle Document
   @param rule  {type: category}
   @param key   the structure key
   @return None
   """
   data = battle.data_of(doc, key)
   items = [(k, v) for k, v in data.items() if k != key]
   keys = [k for k, _v in items]
   at = keys.index(CATEGORIES_KEY) + 1 if CATEGORIES_KEY in keys else len(items)
   items.insert(at, (key, rule))
   data.clear()
   data.update(items)


def _type_majority(doc: Document, damaging: list[str], default: str | None) -> JsonDict:
   """!Each type's most common damaging category among its moves (ties and types without damaging moves: the
   default, else the first damaging one).
   @param doc       battle Document
   @param damaging  damaging_categories()
   @param default   a damaging category, or None
   @return {type: category} in type order
   """
   moves = _moves(doc)
   rule: JsonDict = {}
   for t in _type_names(doc):
      counts = {c: sum(1 for m in moves if m.get("type") == t and category_of(doc, m) == c) for c in damaging}
      most = max(counts.values())
      rule[t] = next(c for c in damaging if counts[c] == most) if most else (default or damaging[0])
   return rule


def set_mode(doc: Document, wanted: str, default: str | None = None) -> int:
   """!Switches where damaging moves take their category from.
   To BY_TYPE: each type gets the damaging category most of its damaging moves have (else @p default, else the
   first damaging one); a damaging move then states none, a move of another damaging category than its type's is
   counted (it takes its type's), and a move that took a non-damaging first category by default names it. To
   BY_MOVE: each move names the category its type gave it (when that is not the first: every move keeps its
   category), and the rule goes.
   @param doc      battle Document
   @param wanted   BY_MOVE or BY_TYPE
   @param default  BY_TYPE: the category of a type without damaging moves, or None for the first damaging one
   @return moves whose category changed (BY_TYPE: damaging moves of another category than their type's)
   @throws DocumentError for an unknown mode, no damaging category or a default that is not one
   """
   if wanted not in modes():
      raise DocumentError(f"unknown mode {wanted!r} (one of {', '.join(modes())})")
   if wanted == mode(doc):
      return 0
   moves = _moves(doc)
   rows = _listed(doc)
   first = rows[0].get("name") if rows else None
   if wanted == BY_MOVE:
      for m in moves:
         taken = category_of(doc, m)
         if "category" not in m and taken != first:
            m["category"] = taken
      battle.data_of(doc, BY_TYPE_KEY).pop(BY_TYPE_KEY, None)
      return 0
   damaging = damaging_categories(doc)
   if not damaging:
      raise DocumentError("no damaging category (one with offense and defense) for the types to name")
   if default is not None and default not in damaging:
      raise DocumentError(f"{default!r} is not a damaging category ({', '.join(damaging)})")
   # the most common damaging category of the type's moves; ties and types without moves take the default
   rule = _type_majority(doc, damaging, default)
   # category_by_type gives the hit types' categories too (the engine refuses both tables)
   if hit_available():
      battle.data_of(doc, hit_key()).pop(hit_key(), None)
   changed = 0
   for m in moves:
      taken = category_of(doc, m)
      if taken in damaging:
         changed += int(taken != rule.get(m.get("type")))
         m.pop("category", None)
      else:
         m["category"] = taken   # a status move names its category: none would take its type's
   _place_rule(doc, rule)
   return changed


def set_type_category(doc: Document, type_name: str, category: str) -> int:
   """!Sets the damaging category one type gives its damaging moves (BY_TYPE mode); moves of that type naming
   another damaging category stop naming it (they take the type's).
   @param doc        battle Document
   @param type_name  a type
   @param category   a damaging category
   @return moves whose category changed
   @throws DocumentError in BY_MOVE mode, for an unknown type or a category that is not damaging
   """
   rule = by_type(doc)
   if rule is None:
      raise DocumentError(f"moves name their category: switch to the {BY_TYPE} mode first")
   if type_name not in _type_names(doc):
      raise DocumentError(f"no type {type_name!r}")
   damaging = damaging_categories(doc)
   if category not in damaging:
      raise DocumentError(f"{category!r} is not a damaging category ({', '.join(damaging)})")
   rule[type_name] = category
   changed = 0
   for m in _moves(doc):
      if m.get("type") == type_name and m.get("category") in damaging:
         changed += int(m["category"] != category)
         m.pop("category")
   return changed


def type_added(doc: Document, type_name: str) -> None:
   """!Gives a new type the first damaging category in BY_TYPE mode, and in the hit types' table (core.battle
   add_entry(): both name every type).
   @param doc        battle Document
   @param type_name  the new type
   @return None
   """
   for rule in (by_type(doc), hit_table(doc)):
      if rule is not None and type_name not in rule:
         damaging = damaging_categories(doc)
         if damaging:
            rule[type_name] = damaging[0]


# -- the hit types' categories --------------------------------------------------------------------------

def hit_key() -> str:
   """!The structure key of the hit types' categories (the engine's HIT_CATEGORY_KEY, "hit_category_by_type").
   @return the key
   """
   return str(_bc().HIT_CATEGORY_KEY)


def hit_available() -> bool:
   """!Whether this engine has the hit types' categories (its structure keys name the key).
   @return True from the hit categories on
   """
   return hasattr(_bc(), "HIT_CATEGORY_KEY") and hit_key() in _bc().STRUCTURE_KEYS


def hit_table(doc: Document) -> JsonDict | None:
   """!The structure's hit types' categories (live: change it only inside an edit()).
   @param doc  battle Document
   @return {type: category}, or None when the structure gives none
   """
   if not hit_available():
      return None
   given = battle.data_of(doc, hit_key()).get(hit_key())
   return given if isinstance(given, dict) else None


def hit_rows(doc: Document) -> list[JsonDict]:
   """!The hit types' categories per type (empty without the table).
   @param doc  battle Document
   @return [{"type", "category" (None when the table leaves it out)}] in type order
   """
   rule = hit_table(doc)
   return [{"type": t, "category": rule.get(t)} for t in _type_names(doc)] if rule is not None else []


def set_hit(doc: Document, on: bool, default: str | None = None) -> bool:
   """!Turns the hit types' categories on (each type its moves' most common damaging category, else @p default,
   else the first damaging one) or off (BY_MOVE mode: in BY_TYPE mode category_by_type gives them).
   @param doc      battle Document
   @param on       True: the table; False: none (a move whose type changes keeps its category)
   @param default  the category of a type without damaging moves, or None
   @return True when it changed
   @throws DocumentError when the engine has no such table, in BY_TYPE mode, or for a default that is not damaging
   """
   if not hit_available():
      raise DocumentError("this engine has no hit types' categories")
   if not on:
      return battle.data_of(doc, hit_key()).pop(hit_key(), None) is not None
   if hit_table(doc) is not None:
      return False
   if mode(doc) == BY_TYPE:
      raise DocumentError(f"{BY_TYPE_KEY} already gives the hit types' categories (the category comes from the type)")
   damaging = damaging_categories(doc)
   if not damaging:
      raise DocumentError("no damaging category (one with offense and defense) for the types to name")
   if default is not None and default not in damaging:
      raise DocumentError(f"{default!r} is not a damaging category ({', '.join(damaging)})")
   _place_rule(doc, _type_majority(doc, damaging, default), hit_key())
   return True


def set_hit_category(doc: Document, type_name: str, category: str) -> None:
   """!Sets the damaging category a type gives a hit whose type is not its move's own.
   @param doc        battle Document
   @param type_name  a type
   @param category   a damaging category
   @return None
   @throws DocumentError without the table, for an unknown type or a category that is not damaging
   """
   rule = hit_table(doc)
   if rule is None:
      raise DocumentError("the structure gives no hit types' categories: turn them on first")
   if type_name not in _type_names(doc):
      raise DocumentError(f"no type {type_name!r}")
   damaging = damaging_categories(doc)
   if category not in damaging:
      raise DocumentError(f"{category!r} is not a damaging category ({', '.join(damaging)})")
   rule[type_name] = category


def check_hit(doc: Document) -> None:
   """!Checks the hit types' categories with the engine's compile_hit_category_by_type().
   @param doc  battle Document
   @return None
   @throws DocumentError naming what the compiler refuses
   """
   bc = _bc()
   rule = hit_table(doc)
   if rule is None:
      return
   stats = battle.data_of(doc, "stats").get("stats")
   shape = [{"name": st.get("name"), "pool": st.get("pool") is True}
            for st in (stats if isinstance(stats, list) else []) if isinstance(st, dict)]
   rows = _listed(doc)
   types = battle.data_of(doc, TYPES_KEY).get(TYPES_KEY)
   try:
      compiled = bc.compile_categories(rows, shape, battle.STRUCTURE_FILE)
      bc.compile_hit_category_by_type(rule, types if isinstance(types, list) else [], rows, compiled,
                                      None, battle.STRUCTURE_FILE)
   except bc.ManifestError as e:
      raise DocumentError(str(e)) from None


def _check_stats(doc: Document, offense: Any, defense: Any) -> tuple[str | None, str | None]:
   """!A category's damage stats: both stats (not the pool stat) or neither.
   @param doc      battle Document
   @param offense  stat name or None
   @param defense  stat name or None
   @return (offense, defense)
   @throws DocumentError when they are not
   """
   if (offense is None) != (defense is None):
      raise DocumentError("a damaging category names both offense and defense (neither: non-damaging)")
   usable = damage_stats(doc)
   for what, stat in (("offense", offense), ("defense", defense)):
      if stat is not None and stat not in usable:
         raise DocumentError(f"{what} is a stat other than the pool stat ({', '.join(usable)}; got {stat!r})")
   return offense, defense


def add_category(doc: Document, name: str, offense: str | None = None, defense: str | None = None,
                 index: int | None = None) -> int:
   """!Adds a category.
   @param doc      battle Document
   @param name     its name (not taken)
   @param offense  the stat its damage attacks with, or None (non-damaging)
   @param defense  the stat its damage meets, or None
   @param index    position, or None for the end
   @return its index
   @throws DocumentError for a taken name, a full list or stats the engine refuses
   """
   if not isinstance(name, str) or not name.strip():
      raise DocumentError("names can't be empty")
   name = name.strip()
   if name in [c.get("name") for c in _listed(doc)]:
      raise DocumentError(f"there is already a category {name!r}")
   most = max_categories()
   if len(_listed(doc)) >= most:
      raise DocumentError(f"at most {most} categories (the engine's limit)")
   offense, defense = _check_stats(doc, offense, defense)
   entry: JsonDict = {"name": name}
   if offense is not None:
      entry.update({"offense": offense, "defense": defense})
   lst = battle.entries(doc, CATEGORIES_KEY)
   at = len(lst) if index is None else max(0, min(len(lst), int(index)))
   lst.insert(at, entry)
   return at


def set_damage(doc: Document, name: str, offense: str | None, defense: str | None) -> None:
   """!Sets the stats a category's damage uses (both None: non-damaging).
   @param doc      battle Document
   @param name     category name
   @param offense  stat or None
   @param defense  stat or None
   @return None
   """
   e = battle.entry(doc, CATEGORIES_KEY, name)
   offense, defense = _check_stats(doc, offense, defense)
   tables = [(BY_TYPE_KEY, by_type(doc))] + ([(hit_key(), hit_table(doc))] if hit_available() else [])
   for key, rule in tables:
      users = [t for t, c in (rule or {}).items() if c == name]
      if offense is None and users:
         raise DocumentError(f"category {name!r} is the damaging category of type(s) {', '.join(users)} ({key})")
   if offense is None:
      e.pop("offense", None)
      e.pop("defense", None)
   else:
      e["offense"] = offense
      e["defense"] = defense


def rename_category(doc: Document, old: str, new: str) -> int:
   """!Renames a category; moves, rules.self_hit.category, category_by_type and the effect logic follow.
   @param doc  battle Document
   @param old  current name
   @param new  new name
   @return references updated
   """
   return battle.rename_entry(doc, CATEGORIES_KEY, old, new)


def remove_category(doc: Document, name: str) -> None:
   """!Removes a category nothing names (a move giving no category names the first).
   @param doc   battle Document
   @param name  category name
   @return None
   """
   rows = category_rows(doc)
   row = next((r for r in rows if r["name"] == name), None)
   if row is not None and row["index"] == 0 and row["moves"]:
      raise DocumentError(f"category {name!r} is the first: {row['moves']} move(s) take it (by name or by default)")
   battle.remove_entry(doc, CATEGORIES_KEY, name)


def move_category(doc: Document, name: str, delta: int) -> bool:
   """!Moves a category up or down (its engine index). No move's category changes: in BY_MOVE mode a move that
   names none takes the first, so when the first changes those moves get the old first's name written in the
   same step (they keep their category; the alternative, refusing, would block reordering).
   @param doc    battle Document
   @param name   category name
   @param delta  -1 up, +1 down
   @return True if it moved
   """
   return battle.move_entry(doc, CATEGORIES_KEY, name, delta)


def keep_default(doc: Document, first: str | None) -> int:
   """!After the categories were reordered: in BY_MOVE mode the moves that name no category take the first, so
   when the first is another one now they get the old first's name written (their category stays).
   @param doc    battle Document (inside the edit that reordered)
   @param first  the first category's name before the reorder
   @return moves that got their category written
   """
   listed = _listed(doc)
   if mode(doc) != BY_MOVE or not isinstance(first, str) or not listed or listed[0].get("name") == first:
      return 0
   pinned = [m for m in _moves(doc) if "category" not in m]
   for m in pinned:
      m["category"] = first
   return len(pinned)


def category_line(row: CategoryRow) -> str:
   """!A category as one line of text.
   @param row  a category_rows() row
   @return the line
   """
   damage = f"{row['offense']} vs {row['defense']}" if row["damaging"] else "no formula damage"
   extra = ", rules.self_hit" if row["self_hit"] else ""
   types = f"; types {', '.join(row['types'])}" if row.get("types") else ""
   return f"{row['index']} {row['name']}: {damage}; {row['moves']} move(s){extra}{types}"


def report(doc: Document) -> list[str]:
   """!The categories as text lines, then the budget and the mode (BY_TYPE: one line per type).
   @param doc  battle Document
   @return lines
   """
   rows = category_rows(doc)
   how = "comes from its type (category_by_type)" if mode(doc) == BY_TYPE else f"comes from the {BY_MOVE}"
   lines = [category_line(r) for r in rows] + [f"{len(rows)}/{max_categories()} categories; a damaging move's "
                                               f"category {how}"]
   lines += [f"  {r['type']}: {r['category']} ({r['moves']} damaging move(s))" for r in type_rows(doc)]
   hits = hit_rows(doc)
   if hits:
      lines.append(f"a hit whose type is not its move's own takes that type's category ({hit_key()}):")
      lines += [f"  {r['type']}: {r['category']}" for r in hits]
   return lines
