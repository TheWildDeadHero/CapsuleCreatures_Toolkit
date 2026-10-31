"""!The editor panels available to hosts.

PANELS lists the panel classes in tab order. A host (the scene editor
window, or later the monolithic Studio application) creates the ones it
wants; each is independent of the others.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .animation import AnimationPanel
from .credits import CreditsPanel
from .doors import DoorPanel
from .fonts import FontPanel
from .manifest import ManifestPanel
from .menu_styles import MenuStylePanel
from .screen_graphics import ScreenGraphicsPanel
from .screen_plans import ScreenPlanPanel
from .text import TextPanel
from .text_boxes import TextBoxPanel
from .text_tables import TextTablesPanel

if TYPE_CHECKING:
   from ..panel import EditorPanel

## Panel classes, in tab order ([S2] engine I4: text tables, fonts, text box styles, the manifest's includes;
## [S3] engine DS1: door animations after the sprites; [S5] engine N3: menu styles after the text box styles;
## [S6] engine UC: screen graphics and screen plans after the menu styles).
PANELS = [AnimationPanel, DoorPanel, TextPanel, CreditsPanel, TextTablesPanel, FontPanel, TextBoxPanel, MenuStylePanel,
          ScreenGraphicsPanel, ScreenPlanPanel, ManifestPanel]


def by_id(panel_id: str) -> type[EditorPanel] | None:
   """!A panel class by its panel_id.
   @param panel_id  e.g. "animation"
   @return the class, or None
   """
   return next((p for p in PANELS if p.panel_id == panel_id), None)
