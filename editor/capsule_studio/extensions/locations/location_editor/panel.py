"""!The Locations panel (D-17): the world's default warp transition, banner
styles, locations with their banner and previews, and the shown map's
location.

Shown on its own as the location editor app, and as a tab of the Studio's
World page (its Map box follows the Map tab there). The left column holds the world's
transition and its banner styles (a plain box in its colors, or a 24x24
frame image); the right column its locations (the banner's text, its style,
the preview: when it shows and its sequences, each with the encounter
conditions it waits for) and the location of the map chosen in the Map tab.
Every change goes through the host's run_edit() on the Document it changes,
so Undo / Redo, the unsaved mark and Save work as in the other panels;
renaming or removing a location changes the maps naming it too (one undo
step per file). Everything here is also a `capsule-studio locations`
command (commands.py).
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6 import QtWidgets

from capsule_studio.core import engine, locations
from capsule_studio.core.document import DocumentError
from capsule_studio.ui.panel import EditorPanel
from capsule_studio.ui.widgets import button, set_enabled

if TYPE_CHECKING:
   from PySide6 import QtGui

   from capsule_studio.core.document import Document
   from capsule_studio.core.world import Project
   from capsule_studio.ui.world_shell import WorldWindow

## A JSON object (a preview entry).
JsonDict = dict[str, Any]
## A banner style field's value (None removes the field; a frame may be a Path).
StyleValue = int | str | Path | None

## Errors meaning the engine (its compilers) is missing or too old.
ENGINE_ERRORS = (engine.EngineNotFound, ImportError, AttributeError)
## Preview chooser entries: no preview, then locations.SHOWS.
PREVIEW_CHOICES = ["no preview"] + list(locations.SHOWS)
## Item data role holding an entry's key (Qt.ItemDataRole.UserRole).
ITEM_KEY_ROLE = 256
## Longest a banner may stay, in frames.
MAX_BANNER_FRAMES = locations.MAX_BANNER_FRAMES
## Most frames a banner may take to slide in.
MAX_BANNER_SLIDE = locations.MAX_BANNER_SLIDE
## Tallest the banner style list grows (pixels).
STYLE_LIST_HEIGHT = 110
## Tallest the location list grows (pixels).
LOCATION_LIST_HEIGHT = 130
## Tallest the preview sequence list grows (pixels).
SEQUENCE_LIST_HEIGHT = 90
## Stretch of the left column (transition and banner styles).
LEFT_STRETCH = 2
## Stretch of the right column (map and locations).
RIGHT_STRETCH = 3


class LocationsPanel(EditorPanel):
   """!Edits locations, banner styles and the default transition (core.locations)."""

   ## See EditorPanel.panel_id.
   panel_id = "locations"
   ## See EditorPanel.title.
   title = "Locations"

   def __init__(self, host: WorldWindow, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost with a project
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The map whose location is shown, or None.
      self.map_name = None
      ## True while widgets are being filled.
      self._filling = False
      ## The Document of the last edit from this tab.
      self._last_doc = None

      # -- world
      world = QtWidgets.QGroupBox("World")
      wf = QtWidgets.QFormLayout(world)
      ## Default warp transition.
      self.transition = QtWidgets.QComboBox()
      self.transition.addItems(locations.TRANSITIONS)
      self.transition.setToolTip("The transition of warps that name none (the Events tab sets a warp's own)")
      self.transition.activated.connect(lambda _i: self._world_edit(
         "Set transition", lambda p: locations.set_transition(p, self.transition.currentText())))
      wf.addRow("Warp transition", self.transition)

      # -- banner styles
      styles_box = QtWidgets.QGroupBox("Banner styles")
      sl = QtWidgets.QVBoxLayout(styles_box)
      ## The world's banner styles.
      self.style_list = QtWidgets.QListWidget()
      self.style_list.setMaximumHeight(STYLE_LIST_HEIGHT)
      self.style_list.currentRowChanged.connect(lambda _r: self._style_chosen())
      sl.addWidget(self.style_list)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add", lambda: self.add_style()))
      row.addWidget(button("Remove", lambda: self.remove_style(), "Only a style no location uses"))
      sl.addLayout(row)
      sf = QtWidgets.QFormLayout()
      ## Style name.
      self.style_name = QtWidgets.QLineEdit()
      self.style_name.editingFinished.connect(lambda: self._style_renamed())
      ## Frame image ("" = a plain box).
      self.style_frame = QtWidgets.QLineEdit()
      self.style_frame.setPlaceholderText("none: a plain box in the colors")
      self.style_frame.setToolTip("A 24x24 PNG (3x3 tiles: corners, edges, interior), relative to the world "
                                  "file; its pixels in the fill color become the text background")
      self.style_frame.editingFinished.connect(
         lambda: self._set_style(frame=self.style_frame.text().strip() or None))
      frame_row = QtWidgets.QHBoxLayout()
      frame_row.addWidget(self.style_frame, 1)
      frame_row.addWidget(button("...", lambda: self.choose_frame(), "Choose the frame image"))
      sf.addRow("Name", self.style_name)
      sf.addRow("Frame", frame_row)
      ## Color fields {key: QLineEdit}.
      self.style_colors = {}
      for k in locations.COLORS:
         edit = QtWidgets.QLineEdit()
         edit.setPlaceholderText(locations.STYLE_DEFAULTS[k])
         # the defaults bind this key and field (a plain closure would see the last ones)
         edit.editingFinished.connect(lambda k=k, edit=edit: self._set_style(**{k: edit.text().strip() or None}))
         self.style_colors[k] = edit
         sf.addRow(k.capitalize(), edit)
      ## Frames the banner stays.
      self.style_frames = QtWidgets.QSpinBox()
      self.style_frames.setRange(1, MAX_BANNER_FRAMES)
      self.style_frames.setKeyboardTracking(False)
      self.style_frames.valueChanged.connect(lambda v: self._set_style(frames=v))
      ## Frames it slides in.
      self.style_slide = QtWidgets.QSpinBox()
      self.style_slide.setRange(1, MAX_BANNER_SLIDE)
      self.style_slide.setKeyboardTracking(False)
      self.style_slide.valueChanged.connect(lambda v: self._set_style(slide=v))
      sf.addRow("Shown for (frames)", self.style_frames)
      sf.addRow("Slides in (frames)", self.style_slide)
      sl.addLayout(sf)
      ## Style form widgets.
      self.style_widgets = [self.style_name, self.style_frame, self.style_frames, self.style_slide] + \
          list(self.style_colors.values())

      # -- locations
      loc_box = QtWidgets.QGroupBox("Locations")
      ll = QtWidgets.QVBoxLayout(loc_box)
      ## The world's locations.
      self.loc_list = QtWidgets.QListWidget()
      self.loc_list.setMaximumHeight(LOCATION_LIST_HEIGHT)
      self.loc_list.currentRowChanged.connect(lambda _r: self._location_chosen())
      ll.addWidget(self.loc_list)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add", lambda: self.add_location()))
      row.addWidget(button("Remove", lambda: self.remove_location(), "Its maps are in no location afterwards"))
      ll.addLayout(row)
      lf = QtWidgets.QFormLayout()
      ## Location key.
      self.loc_key = QtWidgets.QLineEdit()
      self.loc_key.setToolTip("What maps name; renaming it changes them too")
      self.loc_key.editingFinished.connect(lambda: self._location_renamed())
      ## The banner's text.
      self.loc_name = QtWidgets.QLineEdit()
      self.loc_name.setMaxLength(locations.MAX_NAME)
      self.loc_name.editingFinished.connect(lambda: self._set_location(name=self.loc_name.text()))
      ## Banner style ("" = no banner).
      self.loc_banner = QtWidgets.QComboBox()
      self.loc_banner.activated.connect(lambda _i: self._set_location(banner=self.loc_banner.currentText() or None))
      ## When the preview shows.
      self.loc_preview = QtWidgets.QComboBox()
      self.loc_preview.addItems(PREVIEW_CHOICES)
      self.loc_preview.setToolTip("always: every time the player enters the location; first: on the first visit")
      self.loc_preview.activated.connect(lambda _i: self._preview_chosen())
      lf.addRow("Key", self.loc_key)
      lf.addRow("Banner text", self.loc_name)
      lf.addRow("Banner style", self.loc_banner)
      lf.addRow("Preview", self.loc_preview)
      ll.addLayout(lf)
      ll.addWidget(QtWidgets.QLabel("Preview sequences (the last whose conditions all hold plays)"))
      ## The location's preview entries.
      self.seq_list = QtWidgets.QListWidget()
      self.seq_list.setMaximumHeight(SEQUENCE_LIST_HEIGHT)
      self.seq_list.currentRowChanged.connect(lambda _r: self._sequence_chosen())
      ll.addWidget(self.seq_list)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add...", lambda: self.add_sequence(), "A capsule.sequence/1 file"))
      row.addWidget(button("Remove", lambda: self.remove_sequence()))
      ll.addLayout(row)
      qf = QtWidgets.QFormLayout()
      ## The entry's sequence file.
      self.seq_path = QtWidgets.QLineEdit()
      self.seq_path.editingFinished.connect(lambda: self._set_sequence(sequence=self.seq_path.text().strip()))
      ## The entry's conditions (comma separated encounter condition names).
      self.seq_when = QtWidgets.QLineEdit()
      self.seq_when.setPlaceholderText("always (else e.g. night)")
      self.seq_when.setToolTip("Encounter condition names (the world's), comma separated")
      self.seq_when.editingFinished.connect(lambda: self._set_sequence(when=self._when_text()))
      qf.addRow("Sequence", self.seq_path)
      qf.addRow("When", self.seq_when)
      ll.addLayout(qf)
      ## Location form widgets.
      self.loc_widgets = [self.loc_key, self.loc_name, self.loc_banner, self.loc_preview, self.seq_list]

      # -- this map
      map_box = QtWidgets.QGroupBox("Map")
      mf = QtWidgets.QFormLayout(map_box)
      ## The map shown.
      self.map_box = QtWidgets.QComboBox()
      self.map_box.currentTextChanged.connect(lambda t: self._map_chosen(t))
      ## Follow the map chosen in the Map tab.
      self.follow = QtWidgets.QCheckBox("Follow the Map tab")
      self.follow.setChecked(True)
      self.follow.toggled.connect(lambda on: on and self._follow())
      self.follow.setVisible(getattr(host, "shows_map", lambda: True)())   # no Map tab: nothing to follow
      top = QtWidgets.QHBoxLayout()
      top.addWidget(self.map_box, 1)
      top.addWidget(self.follow)
      ## The map's location ("" = none).
      self.map_location = QtWidgets.QComboBox()
      self.map_location.activated.connect(lambda _i: self._set_map_location(self.map_location.currentText()
                                                                             or None))
      mf.addRow("Map", top)
      mf.addRow("Location", self.map_location)

      ## Problems.
      self.problems = QtWidgets.QLabel()
      self.problems.setWordWrap(True)

      left = QtWidgets.QVBoxLayout()
      left.addWidget(world)
      left.addWidget(styles_box)
      left.addStretch(1)
      right = QtWidgets.QVBoxLayout()
      right.addWidget(map_box)
      right.addWidget(loc_box)
      right.addWidget(self.problems)
      right.addStretch(1)
      lay = QtWidgets.QHBoxLayout(self)
      lay.addLayout(left, LEFT_STRETCH)
      lay.addLayout(right, RIGHT_STRETCH)
      self.refresh()

   # -- host ---------------------------------------------------------------------------------

   def project(self) -> Project | None:
      """!The host's world Project.
      @return Project, or None
      """
      return self.host_project()

   def map_doc(self) -> Document | None:
      """!The shown map's Document.
      @return Document, or None
      """
      p = self.project()
      if p is None or self.map_name not in p.map_names():
         return None
      return p.map(self.map_name)

   def current_document(self) -> Document | None:
      """!Undo / Redo target: the document of the last edit from this tab, else the world.
      @return Document, or None
      """
      p = self.project()
      if p is None:
         return None
      last = self._last_doc
      if last is not None and last in p.documents() and (last.undo_label() or last.redo_label()):
         return last
      return p.world

   def _edit(self, label: str, fn: Callable[[], object], doc: Document) -> bool:
      """!Runs an edit through the host.
      @param label  undo label
      @param fn     callable
      @param doc    the Document it changes
      @return True when it went through
      """
      self._last_doc = doc
      try:
         ok = self.host.run_edit(label, fn, doc)
      except DocumentError as e:   # hosts without their own error display
         QtWidgets.QMessageBox.warning(self, "Locations", str(e))
         ok = False
      if not ok:
         self.refresh()
      return ok

   def _world_edit(self, label: str, fn: Callable[[Project], object]) -> bool:
      """!An edit of the world Document.
      @param label  undo label
      @param fn     callable(project)
      @return True when it went through
      """
      p = self.project()
      if self._filling or p is None:
         return False
      return self._edit(label, lambda: fn(p), p.world)

   def _follow(self) -> None:
      """!Switches to the map the host's map panel shows (when following).
      @return None
      """
      sel = getattr(self.host, "selected_map", None)
      name = sel() if callable(sel) and self.follow.isChecked() else None
      if name is not None and name != self.map_name:
         self.map_name = name
         self.refresh()

   def document_replaced(self) -> None:
      """!Another world was opened.
      @return None
      """
      self.map_name = None
      self.refresh()

   def showEvent(self, event: QtGui.QShowEvent) -> None:
      """!Follows the Map tab's map when shown.
      @param event  QShowEvent
      @return None
      """
      super().showEvent(event)
      self._follow()
      self.refresh()

   # -- refresh -------------------------------------------------------------------------------

   def chosen_style(self) -> str | None:
      """!The chosen banner style's name.
      @return name, or None
      """
      item = self.style_list.currentItem()
      return item.data(ITEM_KEY_ROLE) if item is not None else None

   def chosen_location(self) -> str | None:
      """!The chosen location's key.
      @return key, or None
      """
      item = self.loc_list.currentItem()
      return item.data(ITEM_KEY_ROLE) if item is not None else None

   def refresh(self) -> None:
      """!Re-reads the world, its styles and locations, and the shown map.
      @return None
      """
      p = self.project()
      self._filling = True
      try:
         set_enabled(self, p is not None)
         if p is None:
            return
         if self.map_name not in p.map_names():
            self.map_name = p.map_names()[0] if p.map_names() else None
         self.transition.setCurrentText(locations.transition(p))
         self._fill_styles(p)
         self._fill_locations(p)
         self.map_box.clear()
         self.map_box.addItems(p.map_names())
         if self.map_name:
            self.map_box.setCurrentText(self.map_name)
         doc = self.map_doc()
         self.map_location.clear()
         self.map_location.addItem("")
         self.map_location.addItems(list(locations.locations(p)))
         # reads as (map_location(doc) or "") if doc is not None else ""
         self.map_location.setCurrentText(locations.map_location(doc) or "" if doc is not None else "")
         self.map_location.setEnabled(doc is not None)
         self._fill_problems(p)
      finally:
         self._filling = False

   @staticmethod
   def _refill(lst: QtWidgets.QListWidget, items: list[tuple[str, str]], keep: str | None) -> None:
      """!Refills a list, keeping the chosen entry.
      @param lst    QListWidget
      @param items  [(key, text)]
      @param keep   key to choose again, or None
      @return None
      """
      lst.clear()
      for key, text in items:
         item = QtWidgets.QListWidgetItem(text)
         item.setData(ITEM_KEY_ROLE, key)
         lst.addItem(item)
         if key == keep:
            lst.setCurrentItem(item)

   def _fill_styles(self, p: Project) -> None:
      """!The style list and the chosen style's form.
      @param p  Project
      @return None
      """
      keep = self.chosen_style()
      self._refill(self.style_list, [(n, f"{n}: {locations.describe_style(st)}")
                                     for n, st in locations.styles(p).items()], keep)
      name = self.chosen_style()
      st = locations.styles(p).get(name) if name is not None else None
      for w in self.style_widgets:
         set_enabled(w, isinstance(st, dict))   # lists go read-only and keep their scroll bars (also below)
      st = st if isinstance(st, dict) else {}
      self.style_name.setText(name or "")
      self.style_frame.setText(str(st.get("frame", "")))
      for k, edit in self.style_colors.items():
         edit.setText(str(st.get(k, "")))
      # a stored value that is no number (the compiler reports it) shows as 1
      self.style_frames.setValue(st.get("frames", locations.STYLE_DEFAULTS["frames"])
                                 if isinstance(st.get("frames", 0), int) else 1)
      self.style_slide.setValue(st.get("slide", locations.STYLE_DEFAULTS["slide"])
                                if isinstance(st.get("slide", 0), int) else 1)

   def _fill_locations(self, p: Project) -> None:
      """!The location list and the chosen location's form.
      @param p  Project
      @return None
      """
      keep = self.chosen_location()
      self._refill(self.loc_list, [(k, f"{k}: {locations.describe(loc)}")
                                   for k, loc in locations.locations(p).items()], keep)
      key = self.chosen_location()
      loc = locations.locations(p).get(key) if key is not None else None
      for w in self.loc_widgets:
         set_enabled(w, isinstance(loc, dict))
      loc = loc if isinstance(loc, dict) else {}
      self.loc_key.setText(key or "")
      self.loc_name.setText(str(loc.get("name", "")))
      self.loc_banner.clear()
      self.loc_banner.addItem("")
      self.loc_banner.addItems(list(locations.styles(p)))
      self.loc_banner.setCurrentText(str(loc.get("banner", "")))
      pv = loc.get("preview")
      self.loc_preview.setCurrentText(pv.get("show", "always") if isinstance(pv, dict) else PREVIEW_CHOICES[0])
      row = self.seq_list.currentRow()
      self.seq_list.clear()
      seqs = locations.sequences(p, key) if key is not None and isinstance(locations.locations(p).get(key),
                                                                            dict) else []
      for e in seqs:
         self.seq_list.addItem(locations.describe_entry(e))
      if 0 <= row < len(seqs):
         self.seq_list.setCurrentRow(row)
      self._fill_sequence()

   def _fill_sequence(self) -> None:
      """!The chosen preview entry's fields.
      @return None
      """
      e = self._sequence()
      for w in (self.seq_path, self.seq_when):
         set_enabled(w, e is not None)
      e = e or {}
      self.seq_path.setText(str(e.get("sequence", "")))
      when = e.get("when") or []
      self.seq_when.setText(", ".join([when] if isinstance(when, str) else when))

   def _fill_problems(self, p: Project) -> None:
      """!The world's location problems.
      @param p  Project
      @return None
      """
      try:
         found = locations.diagnostics(p)
      except ENGINE_ERRORS as e:
         self.problems.setText(f"error: {e}")
         return
      lines = [f"{d.level}: {d.message}" for d in found]
      self.problems.setText("\n".join(lines) or "No location problems.")

   # -- choosing ----------------------------------------------------------------------------------

   def _style_chosen(self) -> None:
      """!Another style in the list.
      @return None
      """
      p = self.project()
      if self._filling or p is None:
         return
      self._filling = True
      try:
         self._fill_styles(p)
      finally:
         self._filling = False

   def _location_chosen(self) -> None:
      """!Another location in the list.
      @return None
      """
      p = self.project()
      if self._filling or p is None:
         return
      self._filling = True
      try:
         self.seq_list.setCurrentRow(-1)
         self._fill_locations(p)
      finally:
         self._filling = False

   def _sequence(self) -> JsonDict | None:
      """!The chosen preview entry.
      @return its dict, or None
      """
      p = self.project()
      key = self.chosen_location()
      if p is None or key is None or not isinstance(locations.locations(p).get(key), dict):
         return None
      seqs = locations.sequences(p, key)
      row = self.seq_list.currentRow()
      return seqs[row] if 0 <= row < len(seqs) and isinstance(seqs[row], dict) else None

   def _sequence_chosen(self) -> None:
      """!Another preview entry in the list.
      @return None
      """
      if self._filling:
         return
      self._filling = True
      try:
         self._fill_sequence()
      finally:
         self._filling = False

   def _map_chosen(self, name: str) -> None:
      """!Another map in the chooser.
      @param name  map name
      @return None
      """
      if self._filling or not name or name == self.map_name:
         return
      self.follow.setChecked(False)
      self.map_name = name
      self.refresh()

   # -- editing ----------------------------------------------------------------------------------

   def _set_style(self, **fields: StyleValue) -> None:
      """!Changes the chosen style.
      @param fields  {field: value or None}
      @return None
      """
      p = self.project()
      name = self.chosen_style()
      if self._filling or p is None or name is None:
         return
      st = locations.styles(p).get(name) or {}
      # nothing changes: None stands for the default, and a missing field holds the default
      if all(st.get(k, locations.STYLE_DEFAULTS.get(k)) == (locations.STYLE_DEFAULTS.get(k) if v is None else v)
             for k, v in fields.items()):
         return
      self._world_edit("Change banner style", lambda p: locations.set_style(p, name, **fields))

   def _style_renamed(self) -> None:
      """!The style name field.
      @return None
      """
      name = self.chosen_style()
      new = self.style_name.text().strip()
      if self._filling or name is None or not new or new == name:
         return
      if self._world_edit("Rename banner style", lambda p: locations.rename_style(p, name, new)):
         self._choose(self.style_list, new)

   @staticmethod
   def _choose(lst: QtWidgets.QListWidget, key: str) -> None:
      """!Chooses an entry of a list by key (after the refresh an edit schedules, too).
      @param lst  QListWidget
      @param key  its key
      @return None
      """
      for i in range(lst.count()):
         if lst.item(i).data(ITEM_KEY_ROLE) == key:
            lst.setCurrentRow(i)
            return
      item = QtWidgets.QListWidgetItem(key)   # not listed yet: a placeholder the refresh keeps chosen
      item.setData(ITEM_KEY_ROLE, key)
      lst.addItem(item)
      lst.setCurrentItem(item)

   def choose_frame(self) -> None:
      """!Picks the chosen style's frame image.
      @return None
      """
      p = self.project()
      if p is None or self.chosen_style() is None:
         self.explain("Banner frame", "banner style")
         return
      path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Banner frame (24x24)", str(p.base),
                                                      "PNG images (*.png);;All files (*)")
      if path:
         self._set_style(frame=Path(path))

   def add_style(self, name: str | None = None) -> None:
      """!Adds a banner style (asks for its name when none is given).
      @param name  its name, or None to ask
      @return None
      """
      p = self.project()
      if p is None:
         self.explain("Add banner style")
         return
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, "Banner style", "Name:")
         if not ok or not name.strip():
            return
         name = name.strip()
      if self._world_edit("Add banner style", lambda p: locations.add_style(p, name)):
         self._choose(self.style_list, name)

   def remove_style(self) -> None:
      """!Removes the chosen banner style.
      @return None
      """
      name = self.chosen_style()
      if name is None:
         self.explain("Remove banner style", "banner style")
      else:
         self._world_edit("Remove banner style", lambda p: locations.remove_style(p, name))

   def _set_location(self, **fields: str | None) -> None:
      """!Changes the chosen location's name or banner.
      @param fields  name and / or banner (None: no banner)
      @return None
      """
      p = self.project()
      key = self.chosen_location()
      if self._filling or p is None or key is None:
         return
      loc = locations.locations(p).get(key) or {}
      if all(loc.get(k) == v for k, v in fields.items()):
         return
      name = fields.get("name")
      banner = fields["banner"] if "banner" in fields else False   # False keeps the banner
      self._world_edit("Change location", lambda p: locations.set_location(p, key, name, banner))

   def _multi(self, label: str, fn: Callable[[], object]) -> bool:
      """!A change of several documents (one undo step each).
      @param label  title for error messages
      @param fn     callable
      @return True when it went through
      """
      try:
         fn()
      except DocumentError as e:
         QtWidgets.QMessageBox.warning(self, label, str(e))
         self.refresh()
         return False
      p = self.project()
      self._last_doc = p.world if p is not None else None
      self.host.changed()
      return True

   def _location_renamed(self) -> None:
      """!The location key field.
      @return None
      """
      p = self.project()
      key = self.chosen_location()
      new = self.loc_key.text().strip()
      if self._filling or p is None or key is None or not new or new == key:
         return
      if self._multi("Rename location", lambda: locations.rename_location(p, key, new)):
         self._choose(self.loc_list, new)

   def add_location(self, key: str | None = None, name: str | None = None) -> None:
      """!Adds a location (asks for its key and banner text when not given); the shown map
      goes into it when it is in none.
      @param key   its key, or None to ask
      @param name  its banner text, or None to ask
      @return None
      """
      p = self.project()
      if p is None:
         self.explain("Add location")
         return
      if key is None:
         key, ok = QtWidgets.QInputDialog.getText(self, "Location", "Key (what maps name):")
         if not ok or not key.strip():
            return
         key = key.strip()
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, "Location", "Banner text:")
         if not ok or not name.strip():
            return
      banner = next(iter(locations.styles(p)), None)   # the first banner style, if any
      if self._world_edit("Add location", lambda p: locations.add_location(p, key, name, banner)):
         self._choose(self.loc_list, key)

   def remove_location(self) -> None:
      """!Removes the chosen location (its maps are in none afterwards).
      @return None
      """
      p = self.project()
      key = self.chosen_location()
      if p is None or key is None:
         self.explain("Remove location", "location")
      else:
         self._multi("Remove location", lambda: locations.remove_location(p, key))

   def _preview_chosen(self) -> None:
      """!The preview chooser.
      @return None
      """
      key = self.chosen_location()
      if key is None:
         return
      text = self.loc_preview.currentText()
      show = None if text == PREVIEW_CHOICES[0] else text
      self._world_edit("Change preview", lambda p: locations.set_preview(p, key, show))

   def add_sequence(self, path: str | None = None) -> None:
      """!Adds a preview sequence to the chosen location (asks for the file when not given).
      @param path  capsule.sequence/1 file, or None to ask
      @return None
      """
      p = self.project()
      key = self.chosen_location()
      if p is None or key is None:
         self.explain("Add preview sequence", "location")
         return
      if path is None:
         path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Preview sequence", str(p.base),
                                                         "Sequences (*.json);;All files (*)")
         if not path:
            return
      self._world_edit("Add preview sequence", lambda p: locations.add_sequence(p, key, path))

   def remove_sequence(self) -> None:
      """!Removes the chosen preview entry.
      @return None
      """
      key = self.chosen_location()
      row = self.seq_list.currentRow()
      if key is None or self._sequence() is None:
         self.explain("Remove preview sequence", "preview sequence")
      else:
         self._world_edit("Remove preview sequence", lambda p: locations.remove_sequence(p, key, row))

   def _when_text(self) -> list[str] | None:
      """!The When field as condition names.
      @return list, or None for none
      """
      names = [c.strip() for c in self.seq_when.text().split(",") if c.strip()]
      return names or None

   def _set_sequence(self, **fields: str | list[str] | None) -> None:
      """!Changes the chosen preview entry.
      @param fields  sequence and / or when
      @return None
      """
      key = self.chosen_location()
      row = self.seq_list.currentRow()
      e = self._sequence()
      if self._filling or key is None or e is None:
         return
      if all(e.get(k) == v for k, v in fields.items()):
         return
      if "sequence" in fields and not fields["sequence"]:
         return
      sequence = fields.get("sequence")
      when = fields["when"] if "when" in fields else False   # False keeps the conditions
      self._world_edit("Change preview sequence", lambda p: locations.set_sequence(p, key, row, sequence, when))

   def _set_map_location(self, key: str | None) -> None:
      """!The shown map's location chooser.
      @param key  location key, or None
      @return None
      """
      p = self.project()
      doc = self.map_doc()
      if self._filling or p is None or doc is None or locations.map_location(doc) == key:
         return
      self._edit("Set location", lambda: locations.set_map_location(p, doc, key), doc)
