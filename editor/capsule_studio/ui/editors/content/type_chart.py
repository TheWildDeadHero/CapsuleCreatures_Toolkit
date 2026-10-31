"""!The Types panel: the type list and the type chart drawn from the chart's
tiers (click a cell to step it to the next tier, right click to step back;
the tiers, the combine mode and the picker grid are on Structure > Tiers &
Chart).

It edits the host's BattleProject (core.battle) through host.run_edit(); the
engine's battle compiler checks the values and its message shows under the
form.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

from ....core import battle, engine
from ....core.structure import chart as chart_model
from ..battle_common import EntryPanel, set_spin, spin
from ..structure.chart import tier_cell_text, tier_shade

if TYPE_CHECKING:
   from ..battle_common import JsonDict

## Letters of a type name shown in a chart column header.
CHART_HEADER_LETTERS = 5


class TypesPanel(EntryPanel):
   """!Types and the type chart. Click a chart cell to step it to the next
   tier (right click steps back)."""

   ## See EditorPanel.panel_id.
   panel_id = "types"
   ## See EditorPanel.title.
   title = "Types"
   ## See EntryPanel.kind.
   kind = "types"
   ## See BattlePanel.title_kind.
   title_kind = "types"

   def build_form(self, layout: QtWidgets.QVBoxLayout) -> None:
      """!Color field and the chart table.
      @param layout  QVBoxLayout
      @return None
      """
      # a colour index is a byte (TypeData::color: the compiler's U8_MAX)
      ## Presentation color index.
      self.color = spin(0, int(engine.tool("battle_compiler").U8_MAX), lambda v: self.set_field("color", v))
      form = QtWidgets.QFormLayout()
      form.addRow("Color index", self.color)
      layout.addLayout(form)
      layout.addWidget(QtWidgets.QLabel("Type chart: rows attack, columns defend; a cell shows its tier (blank: the "
                                        "default). Click steps to the next tier, right click goes back (tiers: "
                                        "Structure > Tiers & Chart)."))
      ## Attacker x defender grid.
      self.chart = QtWidgets.QTableWidget()
      self.chart.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.chart.cellClicked.connect(lambda r, c: self.step_cell(r, c, 1))
      self.chart.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
      self.chart.customContextMenuRequested.connect(lambda pos: self._right_click(pos))
      layout.addWidget(self.chart, 1)

   def fill_form(self, entry: JsonDict | None) -> None:
      """!Shows the color and the whole chart.
      @param entry  type dict or None
      @return None
      """
      set_spin(self.color, entry.get("color", 0) if entry else 0)
      self.color.setEnabled(entry is not None)
      names = self.names()
      doc = self.battle_doc()
      self.chart.blockSignals(True)
      self.chart.setRowCount(len(names))
      self.chart.setColumnCount(len(names))
      self.chart.setHorizontalHeaderLabels([n[:CHART_HEADER_LETTERS] for n in names])
      self.chart.setVerticalHeaderLabels(names)
      tiers = {r["name"]: r for r in chart_model.tier_list(doc)} if doc is not None else {}
      default = chart_model.default_tier(doc) if doc is not None else None
      for r, a in enumerate(names):
         for c, d in enumerate(names):
            v = battle.chart_value(doc, a, d) if doc is not None else default
            item = QtWidgets.QTableWidgetItem(tier_cell_text(v, default))
            item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            item.setToolTip(f"{a} attacking {d}: {v}")
            shade = tier_shade(tiers.get(v))
            if shade is not None:
               item.setBackground(QtGui.QColor(shade))
            self.chart.setItem(r, c, item)
      self.chart.resizeColumnsToContents()
      self.chart.blockSignals(False)

   def _right_click(self, pos: QtCore.QPoint) -> None:
      """!Steps the clicked cell backwards.
      @param pos  QPoint in the table's viewport
      @return None
      """
      item = self.chart.itemAt(pos)
      if item is not None:
         self.step_cell(item.row(), item.column(), -1)

   def step_cell(self, row: int, col: int, delta: int) -> None:
      """!Changes one chart cell to the next / previous tier (core.structure.chart.step_tier()).
      @param row    attacker row
      @param col    defender column
      @param delta  +1 or -1
      @return None
      """
      names = self.names()
      if not (0 <= row < len(names) and 0 <= col < len(names)):
         return
      doc = self.battle_doc()
      if doc is None or not chart_model.tier_names(doc):
         return
      a, d = names[row], names[col]
      # The next tier in list order, wrapping around; a cell naming no tier starts at the first.
      nxt = chart_model.step_tier(doc, a, d, delta)
      self.edit("Type chart", lambda: battle.set_chart(doc, a, d, nxt))
