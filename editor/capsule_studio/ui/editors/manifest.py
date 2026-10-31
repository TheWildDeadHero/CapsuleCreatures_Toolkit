"""!Manifest panel [S2] (engine I4: capsule.assets/1 "includes" and "text_tables"): the other asset manifests this
one includes and the text tables it lists, with the engine's check of the whole.

Two lists (Includes, Text tables) with Add... / Remove / Up / Down (core.asset_tables: every change is checked by the
engine's expand_manifest(): a cycle, a missing file or a palette defined twice is refused), the tables the manifest
reaches through its includes with their languages, the keys a language lacks that another has, and Check (the
engine's asset compiler over the whole manifest with the game's code page and field placeholders: its fit report's
numbers, the ones the build prints). S4 (engine C10): the build language and its fallback (the manifest's "language"
and "fallback_language", chosen among its tables' languages; the engine's select_language() checks them: several
languages and none named, an unknown language or fallback), the keys each language lacks and how many the fallback
fills in; Check compiles in the chosen build language. Every change is one undo step of the manifest.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6 import QtWidgets

from ...core import asset_tables, engine
from ...core.document import DocumentError
from ..panel import EditorPanel
from ..panes import split_box
from ..widgets import button
from .text_common import session_of

if TYPE_CHECKING:
   from ..panel import PanelHost

## The lists: (manifest key, heading, file filter).
LISTS = (("includes", "Includes (asset manifests)", "Asset manifests (*.json)"),
         ("text_tables", "Text tables", "Text tables (*.json)"))
## Missing keys shown per language.
MISSING_SHOWN = 5
## S4: the language combos' entry for a key left out.
NOT_SET = "(not set)"
## S4: the language keys and their labels.
LANGUAGE_ROWS = (("language", "Build language"), ("fallback_language", "Fallback language"))


class ManifestPanel(EditorPanel):
   """!Edits the manifest's includes and text tables."""

   ## See EditorPanel.panel_id.
   panel_id = "manifest"
   ## See EditorPanel.title.
   title = "Manifest"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The list widget of each key.
      self.lists: dict[str, QtWidgets.QListWidget] = {}
      layout = QtWidgets.QHBoxLayout(self)
      for key, heading, pattern in LISTS:
         box = QtWidgets.QGroupBox(heading)
         v = QtWidgets.QVBoxLayout(box)
         lst = QtWidgets.QListWidget()
         self.lists[key] = lst
         v.addWidget(lst, 1)
         row = QtWidgets.QHBoxLayout()
         row.addWidget(button("Add...", lambda k=key, f=pattern: self.add_entry(k, None, f)))
         row.addWidget(button("Remove", lambda k=key: self.remove_entry(k)))
         row.addWidget(button("Up", lambda k=key: self.move_entry(k, -1)))
         row.addWidget(button("Down", lambda k=key: self.move_entry(k, 1)))
         v.addLayout(row)
         layout.addWidget(box, 1)
      side = QtWidgets.QVBoxLayout()
      # S4 (C10): the build language and its fallback
      lang_box = QtWidgets.QGroupBox("Languages (engine C10)")
      lform = QtWidgets.QFormLayout(lang_box)
      ## The language combos by manifest key.
      self.language_boxes = {}
      for key, label in LANGUAGE_ROWS:
         combo = QtWidgets.QComboBox()
         combo.setToolTip("The language a build takes (the asset compiler's --language wins); a key it lacks takes "
                          "the fallback's text" if key == "language" else
                          "A key the build language lacks takes this language's text")
         combo.activated.connect(lambda _i, k=key: self._language_chosen(k))
         self.language_boxes[key] = combo
         lform.addRow(label, combo)
      ## The engine's verdict on the languages.
      self.language_verdict = QtWidgets.QLabel()
      self.language_verdict.setWordWrap(True)
      lform.addRow(self.language_verdict)
      side.addWidget(lang_box)
      ## The tables reached, with their languages.
      self.reached = QtWidgets.QLabel()
      self.reached.setWordWrap(True)
      ## The engine's check.
      self.result = QtWidgets.QLabel("Check runs the engine's asset compiler over the whole manifest.")
      self.result.setWordWrap(True)
      side.addWidget(self.reached)
      side.addWidget(button("Check", lambda: self.check(), "Compile the whole manifest with the engine (tables, "
                                                           "fonts, includes) and fit its authored texts"))
      side.addWidget(self.result)
      side.addStretch(1)
      holder = QtWidgets.QWidget()
      holder.setLayout(side)
      layout.addWidget(holder, 1)
      split_box(layout, every=True)   # [RZ] the lists | languages and check: the user drags the boundaries

   def refresh(self) -> None:
      """!Re-reads the lists and what the manifest reaches.
      @return None
      """
      for key, lst in self.lists.items():
         current = lst.currentItem().text() if lst.currentItem() is not None else None
         lst.clear()
         entries = asset_tables.entries(self.doc, key)
         lst.addItems(entries)
         if current in entries:
            lst.setCurrentRow(entries.index(current))
      refs = asset_tables.table_set(self.doc)
      langs: dict[str, int] = {}
      for r in refs:
         langs[r.language] = langs.get(r.language, 0) + 1
      listed = sum(1 for r in refs if r.listed)
      text = f"{listed} tables listed, {len(refs) - listed} translations beside them: " + \
         (", ".join(f"{n} {lang or '?'}" for lang, n in langs.items()) or "none")
      if len(langs) > 1:
         s = session_of(self.host)
         if s is not None:
            try:
               docs = {r.path: s.table(r.path) for r in refs}
               fallback = asset_tables.language_setting(self.doc, "fallback_language")
               for lang, keys in asset_tables.missing_translations(docs).items():
                  filled = asset_tables.fallback_keys(docs, lang, fallback)   # S4: the fallback's share
                  note = f" ({len(filled)} from the fallback {fallback})" if filled else ""
                  text += f"\n{lang} lacks {len(keys)} keys{note}, e.g. {', '.join(keys[:MISSING_SHOWN])}"
            except DocumentError as e:
               text += f"\n{e}"
      self.reached.setText(text)
      self._fill_languages()

   def _fill_languages(self) -> None:
      """!S4: the build language and fallback combos and the engine's verdict.
      @return None
      """
      doc = self.doc   # a local alias (Doxygen reads some `doc` uses as a new member)
      s = session_of(self.host)
      docs = s.tables if s is not None else None
      langs = asset_tables.languages(doc, docs) if doc.path is not None else []
      for key, combo in self.language_boxes.items():
         combo.blockSignals(True)
         combo.clear()
         combo.addItems([NOT_SET] + langs)
         combo.setCurrentText(asset_tables.language_setting(doc, key) or NOT_SET)
         combo.setEnabled(bool(langs))
         combo.blockSignals(False)
      if doc.path is None:
         self.language_verdict.setText("")
         return
      problem = asset_tables.language_problem(doc, None, docs)
      build = asset_tables.build_language(doc, None, docs)
      self.language_verdict.setText(f"error: {problem}" if problem else
                                    f"A build takes {build}." if build else "The tables name no language.")
      self.language_verdict.setStyleSheet("color: #c03030;" if problem else "")

   def _language_chosen(self, key: str) -> bool:
      """!S4: a language combo changed (one undo step; the engine's rule must accept it).
      @param key  "language" or "fallback_language"
      @return True when it went through
      """
      doc = self.doc   # a local alias (see _fill_languages())
      text = self.language_boxes[key].currentText()
      value = None if text == NOT_SET else text
      if asset_tables.language_setting(doc, key) == value:
         return False
      return self.set_language(key, value)

   def set_language(self, key: str, value: str | None) -> bool:
      """!S4: sets the build language or the fallback.
      @param key    "language" or "fallback_language"
      @param value  a language of the tables, or None to leave it out
      @return True when it went through
      """
      doc = self.doc
      s = session_of(self.host)
      docs = s.tables if s is not None else None
      done = self._edit("Build language" if key == "language" else "Fallback language",
                        lambda: asset_tables.set_language(doc, key, value, docs))
      self.refresh()
      return done

   def _edit(self, label: str, fn: object) -> bool:
      """!One undo step of the manifest.
      @param label  undo label
      @param fn     the edit
      @return True when it went through
      """
      return self.host.run_edit(label, fn)

   def add_entry(self, key: str, path: str | Path | None = None, pattern: str = "*.json") -> bool:
      """!Adds an include or a table.
      @param key      "includes" or "text_tables"
      @param path     the file, or None to ask
      @param pattern  the file dialog's filter
      @return True when it went through
      """
      if self.doc.path is None:
         self.host.show_status("Save the manifest first: its paths are relative to its folder")
         return False
      if path is None:
         path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Add", str(self.doc.path.parent), pattern)
         if not path:
            return False
      doc = self.doc
      return self._edit("Add include" if key == "includes" else "Add text table",
                        lambda: asset_tables.add_entry(doc, key, path))

   def remove_entry(self, key: str) -> bool:
      """!Removes the selected include or table.
      @param key  "includes" or "text_tables"
      @return True when it went through
      """
      item = self.lists[key].currentItem()
      if item is None:
         return False
      doc, rel = self.doc, item.text()
      return self._edit("Remove", lambda: asset_tables.remove_entry(doc, key, rel))

   def move_entry(self, key: str, step: int) -> bool:
      """!Moves the selected include or table.
      @param key   "includes" or "text_tables"
      @param step  -1 up, 1 down
      @return True when it went through
      """
      item = self.lists[key].currentItem()
      if item is None:
         return False
      doc, rel = self.doc, item.text()
      return self._edit("Move", lambda: asset_tables.move_entry(doc, key, rel, step))

   def check(self) -> dict | None:
      """!The engine's check of the whole manifest.
      @return the fit report, or None when it does not compile
      """
      s = session_of(self.host)
      if s is None:
         self.result.setText("Save the manifest first.")
         return None
      try:
         fit = asset_tables.fit_report(self.doc, s.context.page, s.context.field)   # the manifest's language
      except (DocumentError, engine.EngineNotFound) as e:
         self.result.setText(f"Does not compile: {e}")
         self.result.setStyleSheet("color: #c03030;")
         return None
      self.result.setStyleSheet("")
      self.result.setText(f"Compiles: {fit['assets']} assets; {fit.get('checked', 0)} authored texts checked "
                          f"against their box: {fit.get('over', 0)} lines wider "
                          f"({fit.get('with_placeholders', 0)} lines with placeholders measured without them).")
      return fit
