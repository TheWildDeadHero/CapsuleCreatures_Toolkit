"""!Auto-layout of a designer diagram (D-43 §3): a layered layout in the system's direction, like the tidy-up of
Node-RED and draw.io's "vertical / horizontal flow".

  1. Ranks: each node goes one rank after the furthest node that wires into it (sources are rank 0). When only
     cycles are left (a system that allows them), the first waiting node starts the next rank of them.
  2. Order within a rank: by the average position of the nodes that wire into it (barycentre), sweeping from the
     first rank to the last, so wires cross less.
  3. Positions: ranks are columns (left to right) or rows (top to bottom), RANK_GAP apart; nodes in a rank are
     NODE_GAP apart; everything is snapped to the grid and starts where the laid-out nodes' top-left corner was.

Only the system's own nodes move. Annotations (notes, frames, free shapes) and elements inside frames stay where
they are; so a designer's hand-placed notes survive a tidy-up.
"""
from __future__ import annotations

from .model import Diagram, Element
from .ops import HALVES, snap
from .system import TOP_TO_BOTTOM, DesignerSystem

## Grid spacing of the canvas and of auto-layout (canvas units).
GRID = 20
## Space between ranks (columns or rows).
RANK_GAP = 80
## Space between nodes in one rank.
NODE_GAP = 40


def _movable(diagram: Diagram) -> list[Element]:
   """!The elements auto-layout places: the system's nodes that no frame holds.
   @param diagram  the diagram
   @return elements, in diagram order
   """
   return [e for e in diagram.elements.values() if not e.annotation and e.parent is None]


def ranks(diagram: Diagram, ids: list[str]) -> dict[str, int]:
   """!Each node's rank: one after the furthest node wired into it.
   @param diagram  the diagram
   @param ids      the nodes to rank
   @return id -> rank
   """
   wanted = set(ids)
   before: dict[str, list[str]] = {i: [] for i in ids}
   for k in diagram.links.values():
      if not k.annotation and k.source.element in wanted and k.target.element in wanted:
         before[k.target.element].append(k.source.element)
   after: dict[str, list[str]] = {i: [] for i in ids}
   waiting = {i: len(before[i]) for i in ids}
   for target, sources in before.items():
      for source in sources:
         after[source].append(target)
   rank = {i: 0 for i in ids}
   done: set[str] = set()
   ready = [i for i in ids if waiting[i] == 0]
   while len(done) < len(ids):
      if not ready:
         # Only cycles are left: start from the first node still waiting (its links into the cycle are left out).
         ready = [next(i for i in ids if i not in done)]
      node = ready.pop(0)
      if node in done:
         continue
      done.add(node)
      for target in after[node]:
         if target in done:
            continue
         rank[target] = max(rank[target], rank[node] + 1)
         waiting[target] -= 1
         if waiting[target] <= 0:
            ready.append(target)
   return rank


def auto_layout(system: DesignerSystem, diagram: Diagram) -> list[str]:
   """!Lays the system's nodes out in ranks (see the module's notes).
   @param system   the system
   @param diagram  the diagram (positions change in place)
   @return the ids of the elements placed
   """
   nodes = _movable(diagram)
   if not nodes:
      return []
   ids = [e.element_id for e in nodes]
   origin_x = min(e.pos[0] for e in nodes)
   origin_y = min(e.pos[1] for e in nodes)
   rank = ranks(diagram, ids)
   columns: dict[int, list[str]] = {}
   for i in ids:
      columns.setdefault(rank[i], []).append(i)
   before: dict[str, list[str]] = {i: [] for i in ids}
   for k in diagram.links.values():
      if not k.annotation and k.source.element in before and k.target.element in before:
         before[k.target.element].append(k.source.element)
   # Barycentre sweep: each rank sorted by the mean index of the nodes wired into it (unwired keep their order).
   index: dict[str, float] = {}
   for r in sorted(columns):
      column = columns[r]
      # Python empties a list while sorting it, so the unwired nodes' own places are taken first.
      own = {node: float(n) for n, node in enumerate(column)}

      def key(node: str, own: dict[str, float] = own) -> float:
         """!Where a node wants to be in its rank.
         @param node  its id
         @param own   each node's place in its rank before sorting
         @return the mean index of the nodes before it, else its own place
         """
         prior = [index[p] for p in before[node] if p in index]
         return sum(prior) / len(prior) if prior else own[node]

      column.sort(key=key)
      for n, node in enumerate(column):
         index[node] = float(n)
   vertical = system.direction == TOP_TO_BOTTOM
   sizes = {i: system.element_size(diagram.elements[i]) for i in ids}
   along = origin_y if vertical else origin_x
   for r in sorted(columns):
      column = columns[r]
      # The rank's depth along the flow is its widest (or tallest) node.
      depth = max(sizes[i][1] if vertical else sizes[i][0] for i in column)
      across = origin_x if vertical else origin_y
      for node in column:
         w, h = sizes[node]
         offset = (depth - (h if vertical else w)) // HALVES   # centred in the rank
         pos = (across, along + offset) if vertical else (along + offset, across)
         diagram.elements[node].pos = (snap(pos[0], GRID), snap(pos[1], GRID))
         across += (w if vertical else h) + NODE_GAP
      along += depth + RANK_GAP
   return ids
