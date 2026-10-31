"""!Map groups: the world's tree of folders organising its maps
("map_groups" in capsule.world/1, checked by the engine's map compiler).

A group is {"name", "maps": [map names], "groups": [subgroups]}; each map is
in at most one group, and maps in none are ungrouped (listed after the
groups). A group is addressed by its path: the tuple of group names from the
top, e.g. ("World", "Towns"). The runtime does not use groups yet.

Functions that change a Document must be called inside doc.edit().
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
   from .document import Document

## Deepest nesting (the compiler's MAX_GROUP_DEPTH).
MAX_DEPTH = 8

## A parsed JSON object (the world manifest, a group).
JsonDict = dict[str, Any]
## A group's path: the group names from the top.
GroupPath = tuple[str, ...]
## A node of tree(): ("map", name), or ("group", name, path, children).
TreeNode = tuple[str, str] | tuple[str, str, GroupPath, list["TreeNode"]]


def groups_of(data: JsonDict) -> list[JsonDict]:
   """!The top-level groups.
   @param data  world manifest
   @return list of group dicts (the manifest's own objects)
   """
   g = data.get("map_groups")
   return g if isinstance(g, list) else []


def find(data: JsonDict, path: Sequence[str]) -> JsonDict | None:
   """!A group by its path.
   @param data  world manifest
   @param path  tuple of group names (empty: none)
   @return the group dict, or None
   """
   items, found = groups_of(data), None
   for name in path:
      found = next((g for g in items if g.get("name") == name), None)
      if found is None:
         return None
      items = found.get("groups", [])
   return found


def _children(data: JsonDict, path: Sequence[str]) -> list[JsonDict]:
   """!The list of subgroups of a group (the top level for an empty path), created when missing.
   @param data  world manifest
   @param path  group path
   @return list
   """
   if not path:
      return data.setdefault("map_groups", [])
   g = find(data, path)
   if g is None:
      raise ValueError(f"no group {'/'.join(path)!r}")
   return g.setdefault("groups", [])


def group_of(data: JsonDict, map_name: str) -> GroupPath | None:
   """!The group a map is in.
   @param data      world manifest
   @param map_name  map name
   @return group path, or None when ungrouped
   """
   def walk(items: list[JsonDict], prefix: GroupPath) -> GroupPath | None:
      """!Searches groups and their subgroups, depth first.
      @param items   groups
      @param prefix  their parent's path
      @return the path of the group listing the map, or None
      """
      for g in items:
         p = prefix + (g.get("name"),)
         if map_name in g.get("maps", []):
            return p
         r = walk(g.get("groups", []), p)
         if r is not None:
            return r
      return None

   return walk(groups_of(data), ())


def tree(data: JsonDict, map_names: Sequence[str]) -> list[TreeNode]:
   """!The world's maps as a tree, for map lists.
   @param data       world manifest
   @param map_names  the world's map names, in order
   @return list of nodes: ("group", name, path, children) or ("map", name); groups first, then the
           maps no group lists
   """
   listed = set()

   def walk(items: list[JsonDict], prefix: GroupPath) -> list[TreeNode]:
      """!Nodes of some groups: their subgroups first, then their maps (a map listed twice shows once).
      @param items   groups
      @param prefix  their parent's path
      @return group nodes
      """
      out = []
      for g in items:
         p = prefix + (g.get("name"),)
         kids = walk(g.get("groups", []), p)
         for m in g.get("maps", []):
            if m in map_names and m not in listed:
               listed.add(m)
               kids.append(("map", m))
         out.append(("group", g.get("name"), p, kids))
      return out

   out = walk(groups_of(data), ())
   out += [("map", m) for m in map_names if m not in listed]
   return out


def _check_name(name: Any, siblings: list[JsonDict], ignore: JsonDict | None = None) -> None:
   """!Validates a new group name among its siblings.
   @param name      wanted name (any value; a non-empty str without '/' passes)
   @param siblings  sibling group dicts
   @param ignore    a sibling to leave out (the group being renamed), or None
   @return None
   """
   if not isinstance(name, str) or not name.strip() or "/" in name:
      raise ValueError("a group needs a name without '/'")
   if any(g.get("name") == name for g in siblings if g is not ignore):
      raise ValueError(f"there is already a group {name!r} here")


def add_group(doc: Document, parent: Sequence[str], name: str) -> GroupPath:
   """!Adds an empty group.
   @param doc     world Document
   @param parent  parent group path (empty: top level)
   @param name    group name
   @return the new group's path
   """
   if len(parent) + 1 > MAX_DEPTH:
      raise ValueError(f"groups nest at most {MAX_DEPTH} deep")
   siblings = _children(doc.data, tuple(parent))
   _check_name(name, siblings)
   siblings.append({"name": name, "maps": []})
   return tuple(parent) + (name,)


def rename_group(doc: Document, path: Sequence[str], name: str) -> GroupPath:
   """!Renames a group.
   @param doc   world Document
   @param path  group path
   @param name  new name
   @return the group's new path
   """
   g = find(doc.data, path)
   if g is None:
      raise ValueError(f"no group {'/'.join(path)!r}")
   _check_name(name, _children(doc.data, tuple(path[:-1])), ignore=g)
   g["name"] = name
   return tuple(path[:-1]) + (name,)


def remove_group(doc: Document, path: Sequence[str]) -> None:
   """!Removes a group; its maps and subgroups move up into its parent, in its place.
   @param doc   world Document
   @param path  group path
   @return None
   """
   path = tuple(path)
   g = find(doc.data, path)
   if g is None:
      raise ValueError(f"no group {'/'.join(path)!r}")
   siblings = _children(doc.data, path[:-1])
   i = siblings.index(g)
   kids = g.get("groups", [])
   for k in kids:
      _check_name(k.get("name"), [s for s in siblings if s is not g])
   # The subgroups take the group's place in the list.
   siblings[i:i + 1] = kids
   if path[:-1]:
      parent = find(doc.data, path[:-1])
      parent.setdefault("maps", []).extend(g.get("maps", []))
   # Top-level group removed: its maps become ungrouped (they are simply no longer listed).
   if not doc.data.get("map_groups"):
      doc.data.pop("map_groups", None)


def _drop_map(data: JsonDict, map_name: str) -> None:
   """!Takes a map out of whichever group lists it.
   @param data      world manifest
   @param map_name  map name
   @return None
   """
   def walk(items: list[JsonDict]) -> None:
      """!Removes the map from some groups and their subgroups.
      @param items  groups
      """
      for g in items:
         if map_name in g.get("maps", []):
            g["maps"].remove(map_name)
         walk(g.get("groups", []))

   walk(groups_of(data))


def move_map(doc: Document, map_name: str, path: Sequence[str] | None, index: int | None = None) -> None:
   """!Puts a map into a group (or makes it ungrouped).
   @param doc       world Document
   @param map_name  map name
   @param path      group path, or None / empty for ungrouped
   @param index     position among the group's maps, or None for the end
   @return None
   """
   if map_name not in (doc.data.get("maps") or {}):
      raise ValueError(f"the world has no map {map_name!r}")
   target = find(doc.data, tuple(path)) if path else None
   if path and target is None:
      raise ValueError(f"no group {'/'.join(path)!r}")
   _drop_map(doc.data, map_name)
   if target is not None:
      ms = target.setdefault("maps", [])
      # An index outside the list lands at its nearer end.
      ms.insert(len(ms) if index is None else max(0, min(index, len(ms))), map_name)


def move_group(doc: Document, path: Sequence[str], parent: Sequence[str], index: int | None = None) -> GroupPath:
   """!Moves a group (with everything in it) under another group or to the top level.
   @param doc     world Document
   @param path    group path
   @param parent  new parent path (empty: top level)
   @param index   position among the new siblings, or None for the end
   @return the group's new path
   """
   path, parent = tuple(path), tuple(parent)
   # The new parent is the group itself or one of its descendants when its path starts with the group's.
   if parent[:len(path)] == path:
      raise ValueError("a group cannot go inside itself")
   g = find(doc.data, path)
   if g is None:
      raise ValueError(f"no group {'/'.join(path)!r}")

   def depth(x: JsonDict) -> int:
      """!Levels of a group and its deepest subgroups.
      @param x  group
      @return 1 for a group without subgroups
      """
      return 1 + max((depth(k) for k in x.get("groups", [])), default=0)

   if len(parent) + depth(g) > MAX_DEPTH:
      raise ValueError(f"groups nest at most {MAX_DEPTH} deep")
   new_siblings = _children(doc.data, parent)
   _check_name(g.get("name"), new_siblings, ignore=g)
   old = _children(doc.data, path[:-1])
   pos = old.index(g)
   old.remove(g)
   # Within the same list, positions after the old one moved up by one when it was taken out.
   if old is new_siblings and index is not None and index > pos:
      index -= 1
   new_siblings.insert(len(new_siblings) if index is None else max(0, min(index, len(new_siblings))), g)
   return parent + (g.get("name"),)


def prune(doc: Document) -> int:
   """!Drops group entries naming maps the world no longer lists.
   @param doc  world Document
   @return entries dropped
   """
   names = set(doc.data.get("maps") or {})
   n = 0

   def walk(items: list[JsonDict]) -> None:
      """!Prunes some groups and their subgroups, counting in n.
      @param items  groups
      """
      nonlocal n
      for g in items:
         keep = [m for m in g.get("maps", []) if m in names]
         n += len(g.get("maps", [])) - len(keep)
         g["maps"] = keep
         walk(g.get("groups", []))

   walk(groups_of(doc.data))
   return n
