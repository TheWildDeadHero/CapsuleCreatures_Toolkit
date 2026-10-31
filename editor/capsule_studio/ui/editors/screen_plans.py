"""![S6] The scene editor's Screen plans panel (engine UC, D-33): a full-screen scene's layers, palettes, windows,
sprite sheets, sprites, frame steps and transitions as data (core.screen_plans), previewed as the GBA shows them and
exported as the C++ tables capsule/screen/screen.h takes.

Top: the plans beside the manifest (and in its screens/ folder), New plan, Open, Export C++. Left: the plan's name and
display mode, its sections and their items (Add, Remove, Up / Down: the order things load and sprites are created
in), the frame steps and the open / in / out transitions (a preset word, or a fade object as JSON). Middle: the chosen
item's fields, a form built from the core's field table (the command line takes the same fields). Right: the
preview (background video memory and sprite memory simulated: a map written over tiles shows as the GBA would show
it), with the templates applied later (layers::init()), guides (window outlines, sprite boxes), a transition at any
of its calls and played at the GBA's frame rate; below it what check() finds and the video memory map.

S6b (engine C13a / C13c): below the transitions, how the screen leaves (close(), close_now(), replace() or
replace_now() and the next screen) with an Exit timing tab listing its frames; each window's tree entry shows the
tiles and bytes the screen gives it (its TileBuffer), and a line under the tree the plan's total.

The plan is this panel's own Document (Undo / Redo act on it while the panel is in front; Save saves it with the
manifest); every change goes through the host's run_edit(). Everything here is also a `capsule-studio screen-plan`
command.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from ...core import engine, paths, screen_graphics as sg, screen_plans as sp
from ...core.document import Document
from ..panel import EditorPanel, PanelHost
from ..qtimage import to_qimage
from ..panes import split_box
from ..widgets import PixelView, button, set_enabled

## A parsed JSON object.
JsonDict = dict[str, Any]

## Errors meaning the engine is missing or too old, a file cannot be read, or the plan refuses a change.
ENGINE_ERRORS = (engine.EngineNotFound, ImportError, AttributeError, KeyError, OSError, ValueError)
## Preview zoom.
PREVIEW_ZOOM = 2
## Playback timer interval, milliseconds (about the GBA's 60 frames a second).
TICK_MS = 16
## The preview's transition chooser entry for no fade.
NO_FADE = "(no transition)"
## The asset choosers' entry for none.
NO_ASSET = "(none)"
## Plan file filter.
PLAN_FILTER = "Screen plans (*.screen.json);;All files (*)"
## Header file filter.
HEADER_FILTER = "C++ header (*.h);;All files (*)"
## Section titles in the tree.
SECTION_TITLES = {"layers": "Layers", "palettes": "Palettes", "windows": "Windows", "sheets": "Sprite sheets",
                  "sprites": "Sprites"}
## Tree item data: (section, index or -1 for the section's own node).
ROLE = QtCore.Qt.ItemDataRole.UserRole
## Columns of the transitions table.
TRANSITION_COLUMNS = ("Transition", "Value")
## Colours of errors and warnings in the problems list.
SEVERITY_COLORS = {"error": "#c03030", "warning": "#b08010"}
## Layout stretch of the left, middle and right columns.
LEFT_STRETCH, MIDDLE_STRETCH, RIGHT_STRETCH = 2, 2, 3


def item_label(section: str, index: int, item: JsonDict) -> str:
   """!A tree label for an item.
   @param section  its section
   @param index    its index
   @param item     the item
   @return text
   """
   def v(key: str) -> Any:
      """!A field of the item.
      @param key  the field
      @return its value
      """
      return sp.value(item, section, key)

   if section == "layers":
      what = " ".join(x for x in (item.get("tiles") or "", item.get("tilemap") or "") if x)
      return f"BG{v('bg')}{' (later)' if v('later') else ''}: char {v('char_block')}, screen {v('screen_block')}" + \
         (f"  {what}" if what else "")
   if section == "palettes":
      where = f"OBJ tag {v('tag')}" if v("target") == "obj" else f"BG bank {v('bank')}"
      return f"{item.get('palette') or NO_ASSET} -> {where}"
   if section == "windows":
      st = sp.window_storage(item)   # S6b (C13c): the buffer the screen gives it
      return f"{v('name')}: BG{v('bg')} {v('w')}x{v('h')} at {v('x')},{v('y')}, {st.tiles} tiles {st.size_bytes} B"
   if section == "sheets":
      return f"tag {v('tag')}: {item.get('tiles') or str(v('reserve')) + ' reserved tiles'}"
   return f"{v('name')}: sheet {v('sheet')} at {v('x')},{v('y')}"


class ScreenPlanPanel(EditorPanel):
   """!Edits screen plans (core.screen_plans)."""

   ## See EditorPanel.panel_id.
   panel_id = "screen_plans"
   ## See EditorPanel.title.
   title = "Screen plans"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The open plan, or None.
      self.plan = None
      ## The chosen (section, index); index -1 is a section without an item.
      self.chosen = ("layers", -1)
      ## True while widgets are being filled.
      self._filling = False
      ## The form's widgets by field key.
      self.fields: dict[str, QtWidgets.QWidget] = {}
      ## The transition call the preview shows.
      self.call = 0
      ## The preview waits until the panel shows (edits on other tabs refresh every panel).
      self._stale = False
      ## Playback.
      self.timer = QtCore.QTimer(self)
      self.timer.setInterval(TICK_MS)
      self.timer.timeout.connect(lambda: self._tick())

      # -- top
      ## The plans of the manifest.
      self.plans = QtWidgets.QComboBox()
      self.plans.activated.connect(lambda _i: self._plan_chosen())
      top = QtWidgets.QHBoxLayout()
      top.addWidget(QtWidgets.QLabel("Plan"))
      top.addWidget(self.plans, 1)
      top.addWidget(button("New plan...", lambda: self.new_plan(), "A plan in the manifest's screens/ folder"))
      top.addWidget(button("Open...", lambda: self.open_plan(), "A plan file anywhere"))
      top.addWidget(button("Export C++...", lambda: self.export(),
                           "A header with the plan's tables (layers::Plan, Step, Transition, places and tags)"))

      # -- left
      ## The plan's name.
      self.name = QtWidgets.QLineEdit()
      self.name.setToolTip("snake_case: the export's namespace (NAME_screen)")
      self.name.editingFinished.connect(lambda: self._name_edited())
      ## The display mode.
      self.mode = QtWidgets.QSpinBox()
      self.mode.setRange(0, sp.MODES - 1)
      self.mode.setToolTip("0: four text layers; 1: BG0-BG1 text, BG2 affine; 2: BG2-BG3 affine")
      self.mode.setKeyboardTracking(False)
      self.mode.valueChanged.connect(lambda v: self._plan_edit("Display mode", lambda p: sp.set_mode(p, v)))
      ## Sections and items.
      self.tree = QtWidgets.QTreeWidget()
      self.tree.setHeaderHidden(True)
      self.tree.currentItemChanged.connect(lambda *_a: self._tree_picked())
      ## The frame steps.
      self.steps = QtWidgets.QLineEdit()
      self.steps.setToolTip("The screen's frame order: screen::Step words (tasks, animate, build_oam ...)")
      self.steps.editingFinished.connect(lambda: self._steps_edited())
      ## The transitions.
      self.transitions = QtWidgets.QTableWidget(len(sp.TRANSITIONS), len(TRANSITION_COLUMNS))
      self.transitions.setHorizontalHeaderLabels(list(TRANSITION_COLUMNS))
      self.transitions.horizontalHeader().setStretchLastSection(True)
      self.transitions.verticalHeader().hide()
      self.transitions.setToolTip("A preset (" + ", ".join(sp.PRESETS) + ") or a fade object, e.g. "
                                  '{"mask": "bg", "delay": 1, "from": 0, "to": 16, "color": "#f8f8f8"}')
      self.transitions.itemChanged.connect(lambda it: self._transition_edited(it))
      ## S6b (C13a): how the screen leaves.
      self.exit_call = QtWidgets.QComboBox()
      for call in sp.EXIT_CALLS:
         self.exit_call.addItem(f"{call}()", call)
      self.exit_call.setToolTip("close(): the out fade, then it leaves; close_now(): it faded itself and leaves at "
                                "the end of the frame; replace() / replace_now(): the same, then the next screen")
      self.exit_call.activated.connect(lambda _i: self._exit_edited())
      ## S6b: the screen replace() / replace_now() starts.
      self.exit_next = QtWidgets.QComboBox()
      self.exit_next.setEditable(True)
      self.exit_next.setToolTip("The next screen's plan name (replace / replace_now)")
      self.exit_next.lineEdit().editingFinished.connect(lambda: self._exit_edited())
      self.exit_next.activated.connect(lambda _i: self._exit_edited())
      ## S6b (C13c): the plan's window buffers.
      self.storage = QtWidgets.QLabel()
      self.storage.setToolTip("Tiles the screen gives its windows (window::attach(): a TileBuffer<W, H> each, in its "
                              "arena block)")
      form = QtWidgets.QFormLayout()
      form.addRow("Name", self.name)
      form.addRow("Mode", self.mode)
      rows = QtWidgets.QHBoxLayout()
      rows.addWidget(button("Add", lambda: self.add_item(), "An item in the chosen section"))
      rows.addWidget(button("Remove", lambda: self.remove_item()))
      rows.addWidget(button("Up", lambda: self.move_item(-1)))
      rows.addWidget(button("Down", lambda: self.move_item(1)))
      left = QtWidgets.QVBoxLayout()
      left.addLayout(form)
      left.addWidget(self.tree, 1)
      left.addLayout(rows)
      left.addWidget(self.storage)
      left.addWidget(QtWidgets.QLabel("Frame steps"))
      left.addWidget(self.steps)
      left.addWidget(self.transitions)
      exit_row = QtWidgets.QHBoxLayout()
      exit_row.addWidget(QtWidgets.QLabel("Exit"))
      exit_row.addWidget(self.exit_call)
      exit_row.addWidget(QtWidgets.QLabel("next"))
      exit_row.addWidget(self.exit_next, 1)
      left.addLayout(exit_row)
      split_box(left)   # [RZ] items over frame steps

      # -- middle
      ## What the chosen item is.
      self.form_title = QtWidgets.QLabel()
      ## The chosen item's form.
      self.form_box = QtWidgets.QWidget()
      ## Its layout.
      self.form = QtWidgets.QFormLayout(self.form_box)
      area = QtWidgets.QScrollArea()
      area.setWidgetResizable(True)
      area.setWidget(self.form_box)
      middle = QtWidgets.QVBoxLayout()
      middle.addWidget(self.form_title)
      middle.addWidget(area, 1)

      # -- right
      ## Later templates applied.
      self.later = QtWidgets.QCheckBox("later templates (layers::init())")
      self.later.toggled.connect(lambda _on: self.update_preview())
      ## Guides.
      self.guides = QtWidgets.QCheckBox("guides")
      self.guides.setToolTip("Window outlines and sprite boxes")
      self.guides.toggled.connect(lambda _on: self.update_preview())
      ## Transition shown.
      self.fade = QtWidgets.QComboBox()
      self.fade.addItem(NO_FADE, None)
      for which in sp.TRANSITIONS:
         self.fade.addItem(which, which)
      self.fade.activated.connect(lambda _i: self._fade_chosen())
      ## The call shown.
      self.slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
      self.slider.valueChanged.connect(lambda v: self._call_changed(v))
      ## The call's blend amounts.
      self.call_text = QtWidgets.QLabel()
      ## The picture.
      self.view = PixelView(PREVIEW_ZOOM)
      ## What check() found.
      self.problems = QtWidgets.QListWidget()
      ## The video memory map.
      self.vram = QtWidgets.QPlainTextEdit()
      self.vram.setReadOnly(True)
      self.vram.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
      opts = QtWidgets.QHBoxLayout()
      opts.addWidget(self.later)
      opts.addWidget(self.guides)
      fade_row = QtWidgets.QHBoxLayout()
      fade_row.addWidget(self.fade)
      fade_row.addWidget(self.slider, 1)
      fade_row.addWidget(button("Play", lambda: self.play(), "Play the transition at the GBA's frame rate"))
      info = QtWidgets.QTabWidget()
      info.addTab(self.problems, "Problems")
      info.addTab(self.vram, "Video memory")
      ## S6b: the exit's frames.
      self.exit_frames = QtWidgets.QPlainTextEdit()
      self.exit_frames.setReadOnly(True)
      info.addTab(self.exit_frames, "Exit timing")
      right = QtWidgets.QVBoxLayout()
      right.addLayout(opts)
      right.addLayout(fade_row)
      right.addWidget(self.call_text)
      right.addWidget(self.view, 1)
      right.addWidget(info, 1)
      split_box(right)   # [RZ] picture over problems and memory

      cols = QtWidgets.QHBoxLayout()
      cols.addLayout(left, LEFT_STRETCH)
      cols.addLayout(middle, MIDDLE_STRETCH)
      cols.addLayout(right, RIGHT_STRETCH)
      split_box(cols)   # [RZ] items | form | preview: the user drags the boundaries
      outer = QtWidgets.QVBoxLayout(self)
      outer.addLayout(top)
      outer.addLayout(cols, 1)
      self.refresh()

   # -- documents -----------------------------------------------------------------------------------------------

   def current_document(self) -> Document | None:
      """!Undo / Redo act on the plan while this panel is in front.
      @return the plan, or the manifest
      """
      host = self.host   # a local alias (Doxygen reads the base class's member read here as a new one)
      return self.plan or getattr(host, "document", None)

   def extra_documents(self) -> list[Document]:
      """!The plan (saved with the manifest).
      @return [plan] or []
      """
      return [self.plan] if self.plan is not None else []

   def document_replaced(self) -> None:
      """!Another manifest: its first plan.
      @return None
      """
      self.plan = None
      self.refresh()

   def stop(self) -> None:
      """!Stops playback.
      @return None
      """
      self.timer.stop()

   def set_plan(self, plan: Document | None) -> None:
      """!Shows a plan.
      @param plan  plan Document, or None
      @return None
      """
      self.plan = plan
      self.chosen = ("layers", -1)
      self.refresh()
      self.host.selection_changed()

   def _plan_chosen(self) -> None:
      """!Another plan in the chooser.
      @return None
      """
      path = self.plans.currentData()
      if path is None or (self.plan is not None and self.plan.path == Path(path)):
         return
      try:
         self.set_plan(sp.open_plan(path))
      except ENGINE_ERRORS as e:
         self.host.show_status(str(e))

   def new_plan(self, name: str | None = None) -> bool:
      """!A new plan beside the manifest (asks its name when none is given).
      @param name  snake_case, or None to ask
      @return True when made
      """
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, "New screen plan", "Name (snake_case):", text="menu")
         if not ok or not name.strip():
            return False
      try:
         plan = sp.create(self.doc, name.strip())
      except ENGINE_ERRORS as e:
         self.host.show_status(str(e))
         return False
      self.set_plan(plan)
      return True

   def open_plan(self, path: str | None = None) -> bool:
      """!Opens a plan file (asks for it when none is given).
      @param path  NAME.screen.json, or None to ask
      @return True when opened
      """
      if path is None:
         path, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Open screen plan", "", PLAN_FILTER)
         if not path:
            return False
      try:
         self.set_plan(sp.open_plan(path))
      except ENGINE_ERRORS as e:
         self.host.show_status(str(e))
         return False
      return True

   def export(self, path: str | None = None) -> bool:
      """!Writes the plan's C++ header (asks where when no path is given).
      @param path  NAME.h, or None to ask
      @return True when written
      """
      if self.plan is None:
         return False
      if path is None:
         start = self.plan.path.parent / f"{self.plan.data.get('name', 'screen')}_screen.h" if self.plan.path else ""
         path, _f = QtWidgets.QFileDialog.getSaveFileName(self, "Export screen plan", str(start), HEADER_FILTER)
         if not path:
            return False
      try:
         text = sp.export_cpp(self.plan.data, self.plan.path.name if self.plan.path else "")
         Path(path).write_text(text, encoding="utf-8")
      except ENGINE_ERRORS as e:
         self.host.show_status(str(e))
         return False
      manifest = self.manifest()
      left = sp.check(self.plan.data, manifest) if manifest is not None else []
      self.host.show_status(f"Wrote {path}" + (f" ({len(left)} problem(s) remain: see Problems)" if left else ""))
      return True

   # -- filling -------------------------------------------------------------------------------------------------

   def manifest(self) -> Document | None:
      """!The manifest the plan draws from: the host's when the plan names it, else the plan's own (read only).
      @return Document, or None
      """
      doc = self.doc
      if self.plan is None:
         return doc
      try:
         path = sp.manifest_path(self.plan)
      except sp.PlanError:
         return doc
      if doc is not None and doc.path == path:
         return doc
      try:
         return Document.open(path)
      except (OSError, ValueError):
         return None

   def refresh(self) -> None:
      """!Re-reads the plans, the plan and its preview.
      @return None
      """
      doc = self.doc
      files = sp.plan_files(doc) if doc is not None else []
      if self.plan is None and files:
         try:
            self.plan = sp.open_plan(files[0])
         except ENGINE_ERRORS:
            self.plan = None
      self._filling = True
      try:
         self.plans.clear()
         shown = list(files)
         if self.plan is not None and self.plan.path is not None and self.plan.path not in shown:
            shown.append(self.plan.path)
         for p in shown:
            label = paths.shown(p, doc.base_dir) if doc is not None and doc.base_dir else str(p)
            self.plans.addItem(label, str(p))
         if self.plan is not None and self.plan.path is not None:
            self.plans.setCurrentIndex(self.plans.findData(str(self.plan.path)))
         has = self.plan is not None
         for w in (self.name, self.mode, self.tree, self.steps, self.transitions, self.form_box, self.exit_call,
                   self.exit_next):
            set_enabled(w, has)   # the tree and tables go read-only and keep their scroll bars
         self._fill_exit(files)
         if has:
            data = self.plan.data
            self.name.setText(str(data.get("name", "")))
            self.mode.setValue(int(data.get("mode", 0)))
            self.steps.setText(", ".join(data.get("steps", sp.default_steps())))
            for r, which in enumerate(sp.TRANSITIONS):
               t = sp.transition(data, which)
               head = QtWidgets.QTableWidgetItem(which)
               head.setFlags(head.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
               self.transitions.setItem(r, 0, head)
               self.transitions.setItem(r, 1, QtWidgets.QTableWidgetItem(t if isinstance(t, str) else
                                                                         json.dumps(t)))
         self._fill_tree()
      finally:
         self._filling = False
      self._fill_form()
      self._fade_chosen()

   def _fill_exit(self, files: list[Path]) -> None:
      """!S6b: the exit choosers, the window storage line and the exit's frames.
      @param files  the plans beside the manifest (the next screen's choices)
      @return None
      """
      self.exit_next.clear()
      if self.plan is None:
         self.storage.setText("")
         self.exit_frames.setPlainText("")
         return
      data = self.plan.data
      ex = sp.exit_of(data)
      self.exit_call.setCurrentIndex(max(0, self.exit_call.findData(ex["call"])))
      for path in files:
         try:
            name = json.loads(path.read_text(encoding="utf-8")).get("name")
         except (OSError, ValueError, AttributeError):
            continue
         if isinstance(name, str) and name != data.get("name"):
            self.exit_next.addItem(name)
      self.exit_next.setCurrentText(ex["next"])
      self.exit_next.setEnabled(ex["call"] in sp.REPLACING)
      tiles, size = sp.windows_storage(data)
      self.storage.setText(f"Window buffers: {len(data.get('windows', []))} window(s), {tiles} tiles, {size} bytes")
      try:
         self.exit_frames.setPlainText("\n".join(f"frame {f}: {what}" for f, what in sp.exit_frames(data)))
      except ENGINE_ERRORS as e:
         self.exit_frames.setPlainText(str(e))

   def _exit_edited(self) -> None:
      """!S6b: the exit choosers changed.
      @return None
      """
      if self.plan is None or self._filling:
         return
      call = self.exit_call.currentData()
      nxt = self.exit_next.currentText().strip() if call in sp.REPLACING else ""
      if sp.exit_of(self.plan.data) != {"call": call, "next": nxt}:
         self.set_exit(call, nxt)

   def set_exit(self, call: str, next_screen: str = "") -> bool:
      """!S6b: how the screen leaves.
      @param call         one of sp.EXIT_CALLS
      @param next_screen  replace / replace_now: the next screen's plan name
      @return True when kept
      """
      return self._plan_edit("Exit", lambda p: sp.set_exit(p, call, next_screen))

   def _fill_tree(self) -> None:
      """!The sections and their items, keeping the choice.
      @return None
      """
      self.tree.clear()
      if self.plan is None:
         return
      pick = None
      for section in sp.SECTIONS:
         node = QtWidgets.QTreeWidgetItem([SECTION_TITLES[section]])
         node.setData(0, ROLE, (section, -1))
         self.tree.addTopLevelItem(node)
         if self.chosen == (section, -1):
            pick = node
         for i, item in enumerate(self.plan.data.get(section, [])):
            child = QtWidgets.QTreeWidgetItem([item_label(section, i, item)])
            child.setData(0, ROLE, (section, i))
            node.addChild(child)
            if self.chosen == (section, i):
               pick = child
         node.setExpanded(True)
      if pick is not None:
         self.tree.setCurrentItem(pick)

   def item(self) -> JsonDict | None:
      """!The chosen item.
      @return it, or None
      """
      section, index = self.chosen
      items = self.plan.data.get(section, []) if self.plan is not None else []
      return items[index] if 0 <= index < len(items) else None

   def _fill_form(self) -> None:
      """!The chosen item's fields.
      @return None
      """
      while self.form.rowCount():
         self.form.removeRow(0)
      self.fields.clear()
      section, index = self.chosen
      item = self.item()
      if item is None:
         self.form_title.setText(f"{SECTION_TITLES[section]}: choose an item, or Add one")
         return
      self.form_title.setText(f"{SECTION_TITLES[section]} {index}")
      manifest = self.manifest()
      self._filling = True
      try:
         for f in sp.FIELDS[section]:
            w = self._field_widget(section, f, sp.value(item, section, f.key), manifest)
            w.setToolTip(f.help)
            self.fields[f.key] = w
            self.form.addRow(f.key, w)
      finally:
         self._filling = False

   def _field_widget(self, section: str, f: sp.Field, current: Any, manifest: Document | None) -> QtWidgets.QWidget:
      """!One field's widget, wired to commit its value.
      @param section   the section
      @param f         the field
      @param current   its value
      @param manifest  the manifest (asset choices), or None
      @return the widget
      """
      key = f.key
      if f.kind == sp.INT:
         w = QtWidgets.QSpinBox()
         w.setRange(f.lo, f.hi)
         w.setValue(int(current))
         w.setKeyboardTracking(False)
         w.valueChanged.connect(lambda v: self.set_field(key, v))
      elif f.kind == sp.BOOL:
         w = QtWidgets.QCheckBox()
         w.setChecked(bool(current))
         w.clicked.connect(lambda on: self.set_field(key, bool(on)))
      elif f.kind in (sp.CHOICE, sp.ASSET):
         w = QtWidgets.QComboBox()
         if f.kind == sp.ASSET:
            w.addItem(NO_ASSET, "")
            for k in (sg.keys(manifest, f.choices[0]) if manifest is not None else []):
               w.addItem(k, k)
            if current and w.findData(current) < 0:
               w.addItem(f"{current} (missing)", current)
         else:
            for c in sp.choices_of(f):
               w.addItem(c, c)
         w.setCurrentIndex(max(0, w.findData(current)))
         w.activated.connect(lambda _i, box=w: self.set_field(key, box.currentData()))
      else:
         w = QtWidgets.QLineEdit(str(current))
         w.editingFinished.connect(lambda box=w: self.set_field(key, box.text().strip()))
      return w

   # -- edits ---------------------------------------------------------------------------------------------------

   def _plan_edit(self, label: str, fn: Any) -> bool:
      """!One undo step of the plan.
      @param label  undo label
      @param fn     callable(plan)
      @return True when it went through
      """
      plan = self.plan
      if plan is None or self._filling:
         return False
      ok = self.host.run_edit(label, lambda: fn(plan), document=plan)
      self.host.selection_changed()
      self.refresh()
      return ok

   def set_field(self, key: str, raw: Any) -> bool:
      """!A field of the chosen item.
      @param key  the field
      @param raw  its value
      @return True when kept
      """
      section, index = self.chosen
      if self.item() is None:
         return False
      return self._plan_edit(f"Set {section} {key}", lambda p: sp.set_item(p, section, index, **{key: raw}))

   def add_item(self, section: str | None = None, **fields: Any) -> bool:
      """!Adds an item to a section (the chosen one by default).
      @param section  one of the sections, or None for the chosen
      @param fields   its fields
      @return True when added
      """
      section = section or self.chosen[0]
      at: list[int] = []
      if self._plan_edit(f"Add {section}", lambda p: at.append(sp.add_item(p, section, **fields))) and at:
         self.chosen = (section, at[0])
         self.refresh()
         return True
      return False

   def remove_item(self) -> bool:
      """!Removes the chosen item.
      @return True when removed
      """
      section, index = self.chosen
      if self.item() is None:
         return False
      self.chosen = (section, -1)
      return self._plan_edit(f"Remove {section}", lambda p: sp.remove_item(p, section, index))

   def move_item(self, delta: int) -> bool:
      """!Moves the chosen item up (-1) or down (+1).
      @param delta  -1 or +1
      @return True when moved
      """
      section, index = self.chosen
      if self.item() is None:
         return False
      to: list[int] = []
      ok = self._plan_edit(f"Move {section}", lambda p: to.append(sp.move_item(p, section, index, delta)))
      if ok and to:
         self.chosen = (section, to[0])
         self.refresh()
      return ok

   def _name_edited(self) -> None:
      """!The plan's name was edited.
      @return None
      """
      if self.plan is not None and self.name.text().strip() != self.plan.data.get("name"):
         new = self.name.text().strip()
         self._plan_edit("Plan name", lambda p: sp.set_name(p, new))

   def _steps_edited(self) -> None:
      """!The frame steps were edited.
      @return None
      """
      if self.plan is None:
         return
      steps = [s.strip() for s in self.steps.text().replace(",", " ").split() if s.strip()]
      if steps != self.plan.data.get("steps", sp.default_steps()):
         self._plan_edit("Frame steps", lambda p: sp.set_steps(p, steps))

   def set_transition(self, which: str, text: str) -> bool:
      """!A transition from text: a preset word or a fade object's JSON.
      @param which  open, in or out
      @param text   the text
      @return True when kept
      """
      raw = text.strip()
      try:
         value: Any = json.loads(raw) if raw.startswith("{") else raw
      except ValueError as e:
         self.host.show_status(f"{which}: {e}")
         self.refresh()
         return False
      return self._plan_edit(f"Transition {which}", lambda p: sp.set_transition(p, which, value))

   def _transition_edited(self, it: QtWidgets.QTableWidgetItem) -> None:
      """!A transitions table cell was edited.
      @param it  the cell
      @return None
      """
      if self._filling or it.column() != 1:
         return
      self.set_transition(sp.TRANSITIONS[it.row()], it.text())

   def _tree_picked(self) -> None:
      """!Another section or item.
      @return None
      """
      if self._filling:
         return
      cur = self.tree.currentItem()
      if cur is None:
         return
      self.chosen = tuple(cur.data(0, ROLE))
      self._fill_form()
      self.update_preview()

   # -- preview -------------------------------------------------------------------------------------------------

   def _fade_chosen(self) -> None:
      """!Another transition to show: the slider spans its calls.
      @return None
      """
      self.timer.stop()
      which = self.fade.currentData()
      frames: list[tuple[int, int]] = []
      if which and self.plan is not None:
         try:
            frames = sp.fade_frames(sp.fade_of(sp.transition(self.plan.data, which)), sp.fade_style(self.plan.data))
         except ENGINE_ERRORS:
            frames = []
      self.slider.blockSignals(True)
      self.slider.setRange(0, max(0, len(frames) - 1))
      self.call = min(self.call, max(0, len(frames) - 1))
      self.slider.setValue(self.call)
      self.slider.setEnabled(bool(frames))
      self.slider.blockSignals(False)
      self.update_preview()

   def _call_changed(self, v: int) -> None:
      """!The slider moved.
      @param v  the call
      @return None
      """
      self.call = v
      self.update_preview()

   def play(self) -> None:
      """!Plays the chosen transition from its first call.
      @return None
      """
      if not self.slider.isEnabled():
         return
      self.slider.setValue(0)
      self.timer.start()

   def _tick(self) -> None:
      """!The next call of the transition playing.
      @return None
      """
      if self.slider.value() >= self.slider.maximum():
         self.timer.stop()
         return
      self.slider.setValue(self.slider.value() + 1)

   def showEvent(self, event: QtGui.QShowEvent) -> None:
      """!Draws a preview that waited while the panel was hidden.
      @param event  the show event
      @return None
      """
      super().showEvent(event)
      if self._stale:
         self.update_preview()

   def update_preview(self) -> None:
      """!Draws the plan, lists its problems and its video memory (later, when the panel is hidden).
      @return None
      """
      if not self.isVisible():
         self._stale = True
         return
      self._stale = False
      manifest = self.manifest()
      if self.plan is None or manifest is None:
         self.view.set_image(None)
         self.problems.clear()
         self.vram.setPlainText("")
         self.call_text.setText("")
         return
      data = self.plan.data
      later = self.later.isChecked()
      fade = None
      which = self.fade.currentData()
      try:
         if which:
            fade = sp.fade_at(data, which, self.call)
            self.call_text.setText(f"{which}: call {self.call + 1} of {self.slider.maximum() + 1}, BG "
                                   f"{fade.bg_y if fade else 0} / OBJ {fade.obj_y if fade else 0} of {sp.FULL}"
                                   if fade else f"{which}: no fade")
         else:
            self.call_text.setText("")
         img = sp.render(data, manifest, later, fade, self.guides.isChecked())
         self.view.set_image(to_qimage(*img))
         problems = sp.check(data, manifest, later)
         self.vram.setPlainText("\n".join(sp.vram_lines(data, manifest, later)))
      except ENGINE_ERRORS as e:
         self.view.set_image(None)
         problems = [sp.Problem("error", "plan", str(e))]
      self.problems.clear()
      for p in problems or [sp.Problem("ok", "plan", "no problems")]:
         row = QtWidgets.QListWidgetItem(str(p))
         if p.severity in SEVERITY_COLORS:
            row.setForeground(QtGui.QColor(SEVERITY_COLORS[p.severity]))
         self.problems.addItem(row)
