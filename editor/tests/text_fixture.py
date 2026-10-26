"""!A small neutral game's text for the I4 text tests [S2]: an asset manifest naming a proportional font (simple
box glyphs for printable ASCII, the engine's default code page) and two text tables (en, de), and a scripts manifest
with field placeholders and a term that encode them. make_game() writes it into a folder; the tables and the font
are in Python's json layout (indent 1), as an importer writes them, the manifests in the studio's compact layout.
The asset manifest lists the English table; the German one is its translation in a sibling folder (one manifest holds
one language: a key is one asset).

Imported by test_text_tables, test_fonts, test_text_boxes and test_qt_text_panels; not a test itself.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

## The font's cell (width, height).
CELL = (8, 8)
## Pixels between glyphs.
LETTER_SPACING = 1
## Pixels from one line's top to the next's.
LINE_HEIGHT = 9
## The box: its width in pixels and lines.
BOX_WIDTH, BOX_LINES = 120, 2
## Width of the space glyph.
SPACE_WIDTH = 3
## Narrowest glyph width (each glyph is this plus its code modulo WIDTH_STEPS).
BASE_WIDTH = 3
## Glyph widths cycle through this many values.
WIDTH_STEPS = 4
## First and last printable ASCII code the font covers.
FIRST_CODE, LAST_CODE = 0x20, 0x7E
## Rows of a glyph's box shape (top and bottom rows stay transparent).
SHAPE_TOP, SHAPE_BOTTOM = 1, 6
## The English texts.
EN_TEXTS = {
   "text:Main.Greeting": {"text": "Hello {player}!\nWelcome to {place}.", "wrap": "original"},
   "text:Main.Long": {"text": "Short line\n" + "W" * 40, "wrap": "original"},
   "text:Main.Auto": "A long text the compiler breaks at spaces to fit the box, with pages after two lines of it.",
   "text:Main.Pause": {"text": "Wait{pause:15} here{scroll}next line", "wrap": "original"},
}
## The German texts (one key fewer: a missing translation).
DE_TEXTS = {
   "text:Main.Greeting": {"text": "Hallo {player}!\nWillkommen in {place}.", "wrap": "original"},
   "text:Main.Auto": "Ein langer Text, den der Compiler an Leerzeichen bricht.",
}
## The term the {place} placeholder prints.
TOWN = "Elmwood"


def glyph_width(ch: str) -> int:
   """!A glyph's advance width in the fixture font.
   @param ch  the character
   @return pixels
   """
   return SPACE_WIDTH if ch == " " else BASE_WIDTH + ord(ch) % WIDTH_STEPS


def glyph_rows(ch: str) -> list[str]:
   """!A glyph's rows: a box of ink as wide as the glyph less one column, its right column shadow.
   @param ch  the character
   @return rows of pixel digits
   """
   w, h = CELL
   width = glyph_width(ch)
   rows = []
   for y in range(h):
      if ch == " " or not SHAPE_TOP <= y <= SHAPE_BOTTOM:
         rows.append("0" * w)
         continue
      ink = width - 1
      rows.append(("1" * (ink - 1) + "2").ljust(w, "0")[:w])
   return rows


def font_data() -> dict:
   """!The fixture's capsule.font/2 data.
   @return the JSON object
   """
   glyphs = {chr(c): {"width": glyph_width(chr(c)), "rows": glyph_rows(chr(c))}
             for c in range(FIRST_CODE, LAST_CODE + 1)}
   return {"schema": "capsule.font/2", "name": "body", "cell": list(CELL), "line_height": LINE_HEIGHT,
           "letter_spacing": LETTER_SPACING, "glyphs": glyphs}


def line_width(text: str) -> int:
   """!A line's width in the fixture font (the engine's rule: each glyph's width plus the letter spacing).
   @param text  the line (no markup)
   @return pixels
   """
   return sum(glyph_width(c) + LETTER_SPACING for c in text)


def table(language: str, texts: dict) -> dict:
   """!A text table.
   @param language  its language
   @param texts     its texts
   @return the JSON object
   """
   return {"schema": "capsule.texts/1", "language": language,
           "box": {"font": "body", "width": BOX_WIDTH, "lines": BOX_LINES},
           "fonts": {"body": "../../fonts/body.font.json"}, "texts": texts}


@dataclass
class Game:
   """!Where make_game() put things."""

   ## The game folder.
   root: Path
   ## The asset manifest.
   assets: Path
   ## The English table.
   en: Path
   ## The German table.
   de: Path
   ## The font.
   font: Path
   ## The scripts manifest.
   scripts: Path


def write_layout(path: Path, data: object) -> Path:
   """!Writes JSON in Python's indent-1 layout (an importer's).
   @param path  the file
   @param data  its content
   @return the path
   """
   path.parent.mkdir(parents=True, exist_ok=True)
   path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
   return path


def make_game(folder: Path) -> Game:
   """!Writes the fixture game into a folder.
   @param folder  an empty folder
   @return Game
   """
   from capsule_studio.core import manifest_io
   root = folder / "game"
   font = write_layout(root / "fonts" / "body.font.json", font_data())
   en = write_layout(root / "text" / "en" / "main.json", table("en", EN_TEXTS))
   de = write_layout(root / "text" / "de" / "main.json", table("de", DE_TEXTS))
   assets = root / "assets.json"
   manifest_io.save(assets, {"schema": "capsule.assets/1", "id": "game",
                             "assets": [{"key": "font:BODY", "kind": "font", "font": "fonts/body.font.json"}],
                             "text_tables": ["text/en/main.json"]})
   scripts = root / "scripts" / "scripts.json"
   manifest_io.save(scripts, {"schema": "capsule.scripts/1", "assets": "../assets.json", "sources": [],
                              "placeholders": {"player": {"name": 7}, "place": {"term": "town"}},
                              "terms": {"town": TOWN}})
   return Game(root, assets, en, de, font, scripts)
