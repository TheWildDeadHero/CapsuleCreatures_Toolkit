"""!The Plugin data panel (D-10 §4, plugin API 3): the connector blocks of the game's plugins, edited with a form the
panel builds from each connector's schema.

Shown while the game has a plugin with a connector, as a tab of the Studio's World page and of the map editor. The
left column picks the plugin, the attach point and the record (the project, the world, a map, a layer, a battle
entry, an asset, or a cell of a map: the Map tab's map when there is one); records that carry a block are marked.
The middle column is the inspector: one field per schema entry (numbers, check boxes, choices, text, references
chosen from the game's own names, JSON for lists and nested blocks), each showing its default until set, with the
connector's problems for the record under it. The right column shows the plugin's previews of the record and its
file formats (Import..., Export...).

Every change goes through the host's run_edit() on the Document of the file holding the record (one undo step; an
import is one step over every file it changes), so Undo / Redo, the unsaved mark and Save work as in the other
panels. Everything here is also a `capsule-studio ext` command (commands.py).
"""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtGui, QtWidgets

from capsule_studio.core import engine, plugin_data
from capsule_studio.core.document import DocumentError
from capsule_studio.ui.panel import EditorPanel
from capsule_studio.ui.panes import split_box
from capsule_studio.ui.widgets import button, report_failure, set_enabled

if TYPE_CHECKING:
   from capsule_studio.core.document import Document
   from capsule_studio.ui.world_shell import WorldWindow

## A JSON value.
Json = Any
## A field's editor: (widget, read its value, show a value).
FieldEditor = tuple[QtWidgets.QWidget, Callable[[], Json], Callable[[Json], None]]

## Errors meaning the engine (its tools) is missing or refused something.
ENGINE_ERRORS = (engine.EngineNotFound, ImportError, plugin_data.PluginDataError)
## Item data role holding a record's name (Qt.ItemDataRole.UserRole).
NAME_ROLE = 256
## The reference chooser's entry for no reference.
NO_REF = "(none)"
## Marks a record that carries a block in the record list.
HAS_BLOCK = "● "
## Lines the JSON editor of a list or nested block shows.
JSON_LINES = 4
## Stretch of the left column (records).
RECORDS_STRETCH = 2
## Stretch of the inspector.
INSPECTOR_STRETCH = 3
## Stretch of the right column (previews, formats).
FILES_STRETCH = 2
## Smallest and largest cell coordinate the cell chooser offers (maps reach left of and above 0).
CELL_RANGE = 4096


class PluginDataPanel(EditorPanel):
   """!Edits the game's connector blocks (core.plugin_data)."""

   ## See EditorPanel.panel_id.
   panel_id = "plugin-data"
   ## See EditorPanel.title.
   title = "Plugin data"

   def __init__(self, host: WorldWindow, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost with a project
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The game's plugin data, or None (no world, or a world outside a game).
      self.data = None
      ## True while widgets are being filled (their signals change nothing).
      self._filling = False
      ## The (plugin, point) the form was built for.
      self._form_for = None
      ## Field editors: key -> FieldEditor.
      self._editors = {}
      ## The Document of the chosen record, or None.
      self._doc = None

      outer = QtWidgets.QHBoxLayout(self)

      # -- the records
      left = QtWidgets.QVBoxLayout()
      pick = QtWidgets.QFormLayout()
      ## The plugin chooser.
      self.plugin_box = QtWidgets.QComboBox()
      self.plugin_box.currentIndexChanged.connect(lambda _i: self._plugin_chosen())
      pick.addRow("Plugin", self.plugin_box)
      ## The attach point chooser.
      self.point_box = QtWidgets.QComboBox()
      self.point_box.setToolTip("Where the plugin's blocks go (capsule-studio ext points)")
      self.point_box.currentIndexChanged.connect(lambda _i: self._point_chosen())
      pick.addRow("Attach point", self.point_box)
      left.addLayout(pick)
      ## The cell chooser (cells only): map, x, y.
      self.cell_row = QtWidgets.QWidget()
      cr = QtWidgets.QHBoxLayout(self.cell_row)
      cr.setContentsMargins(0, 0, 0, 0)
      ## The cell's map.
      self.cell_map = QtWidgets.QComboBox()
      self.cell_map.currentIndexChanged.connect(lambda _i: self._fill_records())
      ## The cell's column and row.
      self.cell_x = QtWidgets.QSpinBox()
      ## The cell's row.
      self.cell_y = QtWidgets.QSpinBox()
      for spin in (self.cell_x, self.cell_y):
         spin.setRange(-CELL_RANGE, CELL_RANGE)
      cr.addWidget(self.cell_map, 1)
      cr.addWidget(self.cell_x)
      cr.addWidget(self.cell_y)
      cr.addWidget(button("Go", lambda: self.choose_cell(self.cell_x.value(), self.cell_y.value()),
                          "Show this cell's block (the list shows the cells that have one)"))
      left.addWidget(self.cell_row)
      ## The records of the point.
      self.records = QtWidgets.QListWidget()
      self.records.setToolTip(f"{HAS_BLOCK.strip()}: the record has the plugin's block")
      self.records.currentRowChanged.connect(lambda _r: self._record_chosen())
      left.addWidget(self.records, 1)
      row = QtWidgets.QHBoxLayout()
      ## Adds a block to the chosen record.
      self.add_button = button("Add block", lambda: self.add_block(), "Give the record the plugin's block")
      ## Removes the chosen record's block.
      self.remove_button = button("Remove block", lambda: self.remove_block())
      row.addWidget(self.add_button)
      row.addWidget(self.remove_button)
      left.addLayout(row)
      outer.addLayout(left, RECORDS_STRETCH)

      # -- the inspector
      middle = QtWidgets.QVBoxLayout()
      ## The record's heading.
      self.heading = QtWidgets.QLabel()
      self.heading.setWordWrap(True)
      middle.addWidget(self.heading)
      ## The form's box.
      self.form_box = QtWidgets.QGroupBox("Fields")
      ## The form.
      self.form = QtWidgets.QFormLayout(self.form_box)
      middle.addWidget(self.form_box, 1)
      ## The record's problems.
      self.problems = QtWidgets.QLabel()
      self.problems.setWordWrap(True)
      self.problems.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
      middle.addWidget(self.problems)
      outer.addLayout(middle, INSPECTOR_STRETCH)

      # -- previews and formats
      right = QtWidgets.QVBoxLayout()
      prev = QtWidgets.QGroupBox("Preview")
      pl = QtWidgets.QVBoxLayout(prev)
      ## The preview chooser.
      self.preview_box = QtWidgets.QComboBox()
      self.preview_box.currentIndexChanged.connect(lambda _i: self._show_preview())
      pl.addWidget(self.preview_box)
      ## The preview's text.
      self.preview = QtWidgets.QPlainTextEdit()
      self.preview.setReadOnly(True)
      pl.addWidget(self.preview, 1)
      right.addWidget(prev, 1)
      formats = QtWidgets.QGroupBox("Files")
      fl = QtWidgets.QVBoxLayout(formats)
      ## The format chooser.
      self.format_box = QtWidgets.QComboBox()
      fl.addWidget(self.format_box)
      frow = QtWidgets.QHBoxLayout()
      frow.addWidget(button("Import...", lambda: self.import_file(), "Read a file into the plugin's blocks (one "
                                                                   "undo step)"))
      frow.addWidget(button("Export...", lambda: self.export_file(), "Write the plugin's blocks to a file"))
      fl.addLayout(frow)
      right.addWidget(formats)
      outer.addLayout(right, FILES_STRETCH)
      split_box(outer, every=True)
      self.document_replaced()

   # -- what is shown --------------------------------------------------------------------------------------------

   def _registry(self) -> Any:
      """!The host's plugin registry (formats and previews), or None.
      @return plugins.Registry, or None
      """
      host = self.host   # a local name: Doxygen 1.9 reads "return getattr(self.x" as a new member
      return getattr(host, "extensions", None)

   def plugin_id(self) -> str | None:
      """!The chosen plugin.
      @return its id, or None
      """
      return self.plugin_box.currentData() or None

   def point(self) -> str | None:
      """!The chosen attach point.
      @return it, or None
      """
      return self.point_box.currentText() or None

   def record(self) -> str | None:
      """!The chosen record.
      @return its name ("MAP@x,y" for a cell), or None
      """
      item = self.records.currentItem()
      return item.data(NAME_ROLE) if item is not None else None

   def current_document(self) -> Document | None:
      """!Undo / Redo act on the chosen record's file.
      @return Document, or None
      """
      return self._doc

   def document_replaced(self) -> None:
      """!A world was opened: reads its game's plugins.
      @return None
      """
      project = self.host_project()
      self.data = None
      self._form_for = None
      if project is not None:
         try:
            self.data = plugin_data.for_project(project, getattr(self.host, "shared_document", None))
         except ENGINE_ERRORS as e:
            self.host.show_status(f"Plugin data: {e}")
      self._filling = True
      try:
         self.plugin_box.clear()
         plugins = self._plugins()
         for p in plugins:
            self.plugin_box.addItem(p.title or p.plugin_id, p.plugin_id)
            self.plugin_box.setItemData(self.plugin_box.count() - 1, p.plugin_id, QtCore.Qt.ItemDataRole.ToolTipRole)
      finally:
         self._filling = False
      self._plugin_chosen()

   def _plugins(self) -> list[Any]:
      """!The game's connectors (an error goes to the status bar).
      @return connectors.Plugin list
      """
      if self.data is None:
         return []
      try:
         return self.data.plugins()
      except ENGINE_ERRORS as e:
         self.host.show_status(f"Plugin data: {e}")
         return []

   def _plugin_chosen(self) -> None:
      """!Fills the attach points, previews and formats of the chosen plugin.
      @return None
      """
      if self._filling:
         return
      pid = self.plugin_id()
      reg = self._registry()
      self._filling = True
      try:
         self.point_box.clear()
         self.preview_box.clear()
         self.format_box.clear()
         if pid is not None and self.data is not None:
            self.point_box.addItems(self.data.points(pid))
            for p in reg.previews(pid) if reg is not None else []:
               self.preview_box.addItem(p.title, p.id)
            for f in reg.formats(pid) if reg is not None else []:
               self.format_box.addItem(f"{f.title} (*{f.suffix})", f.id)
      finally:
         self._filling = False
      set_enabled(self, pid is not None)
      self._point_chosen()

   def _point_chosen(self) -> None:
      """!Shows the records of the chosen point (the cell chooser for cells) and builds the form.
      @return None
      """
      if self._filling:
         return
      point = self.point()
      self.cell_row.setVisible(point == "cell")
      if point == "cell" and self.data is not None:
         self._filling = True
         try:
            self.cell_map.clear()
            names = [t.name for t in self.data.targets("cell")]
            self.cell_map.addItems(names)
            shown = getattr(self.host, "selected_map", lambda: None)()
            if shown in names:
               self.cell_map.setCurrentText(shown)
         finally:
            self._filling = False
      self._fill_records()

   def _fill_records(self, keep: str | None = None) -> None:
      """!Lists the records, marking those with a block.
      @param keep  the record to choose (default: the chosen one)
      @return None
      """
      if self._filling:
         return
      keep = keep if keep is not None else self.record()
      pid, point = self.plugin_id(), self.point()
      self._filling = True
      try:
         self.records.clear()
         if pid is not None and point is not None and self.data is not None:
            try:
               with_block = set(self.data.records(pid, point))
               if point == "cell":
                  map_name = self.cell_map.currentText()
                  names = [n for n in sorted(with_block) if n.split("@", 1)[0] == map_name]
                  if keep is not None and keep.startswith(f"{map_name}@") and keep not in names:
                     names.append(keep)   # a cell chosen with Go, without a block yet
               else:
                  names = [t.name for t in self.data.targets(point)]
            except ENGINE_ERRORS as e:
               self.host.show_status(f"Plugin data: {e}")
               names, with_block = [], set()
            for name in names:
               item = QtWidgets.QListWidgetItem((HAS_BLOCK if name in with_block else "   ") + name)
               item.setData(NAME_ROLE, name)
               self.records.addItem(item)
               if name == keep:
                  self.records.setCurrentItem(item)
      finally:
         self._filling = False
      if self.records.currentItem() is None and self.records.count():
         self.records.setCurrentRow(0)
      else:
         self._record_chosen()

   def choose_cell(self, x: int, y: int) -> None:
      """!Chooses a cell of the cell chooser's map (its block, or none yet).
      @param x  column
      @param y  row
      @return None
      """
      map_name = self.cell_map.currentText()
      if not map_name:
         self.explain("Go", "map")
         return
      self._fill_records(keep=f"{map_name}@{x},{y}")

   def choose(self, plugin_id: str, point: str, name: str) -> bool:
      """!Shows one record (tests and other panels).
      @param plugin_id  the plugin
      @param point      the attach point
      @param name       the record ("MAP@x,y" for a cell)
      @return True when it is shown
      """
      self.plugin_box.setCurrentIndex(self.plugin_box.findData(plugin_id))
      self.point_box.setCurrentText(point)
      if point == "cell":
         self.cell_map.setCurrentText(name.split("@", 1)[0])
      self._fill_records(keep=name)
      return self.record() == name

   # -- the inspector ----------------------------------------------------------------------------------------------

   def _record_chosen(self) -> None:
      """!Builds (when the point changed) and fills the form for the chosen record.
      @return None
      """
      if self._filling:
         return
      pid, point, name = self.plugin_id(), self.point(), self.record()
      self._doc = None
      if None in (pid, point) or self.data is None:
         self._build_form(None)
         self.heading.setText("No plugin with a connector is loaded" if self.data is None else "")
         self.problems.clear()
         self._show_preview()
         return
      if self._form_for != (pid, point):
         self._build_form(self.data.schema(pid, point))
         self._form_for = (pid, point)
      block = None
      if name is not None:
         try:
            block = self.data.get(pid, point, name)
            self._doc = self.data.store.document(self.data.target(point, name).path)
         except ENGINE_ERRORS as e:
            self.host.show_status(f"Plugin data: {e}")
      self.heading.setText(f"<b>{point} {name}</b>" + ("" if block is not None else " has no block yet")
                           if name is not None else "Choose a record")
      self.add_button.setEnabled(name is not None and block is None)
      self.remove_button.setEnabled(block is not None)
      self.form_box.setEnabled(block is not None)
      shown = self.data.complete(pid, point, block if block is not None else self.data.new_block(pid, point))
      self._filling = True
      try:
         for key, (_w, _get, show) in self._editors.items():
            show(shown.get(key) if isinstance(shown, dict) else None)
      finally:
         self._filling = False
      self._show_problems(block)
      self._show_preview()
      self.host.selection_changed()

   def _build_form(self, schema: dict[str, Json] | None) -> None:
      """!One editor per field of a block.
      @param schema  the block's description (PluginData.schema()), or None for none
      @return None
      """
      while self.form.rowCount():
         self.form.removeRow(0)
      self._editors.clear()
      for key, f in ((schema or {}).get("fields") or {}).items():
         editor = self._editor(key, f)
         label = QtWidgets.QLabel(f.get("title") or key)
         tip = f.get("help", "") + ("" if "default" not in f else f" (default: {json.dumps(f['default'])})")
         label.setToolTip(tip.strip())
         editor[0].setToolTip(tip.strip())
         self.form.addRow(label, editor[0])
         self._editors[key] = editor

   def _editor(self, key: str, f: dict[str, Json]) -> FieldEditor:
      """!The editor of one field, by its type.
      @param key  the field's key
      @param f    its description
      @return (widget, getter, setter)
      """
      kind = f.get("type")
      if kind == "integer":
         spin = QtWidgets.QSpinBox()
         spin.setRange(f.get("minimum", 0), f.get("maximum", 0))
         spin.setKeyboardTracking(False)
         spin.valueChanged.connect(lambda _v, k=key: self._field_changed(k))
         return spin, spin.value, lambda v, s=spin: s.setValue(v if isinstance(v, int) else s.minimum())
      if kind == "boolean":
         check = QtWidgets.QCheckBox()
         check.toggled.connect(lambda _v, k=key: self._field_changed(k))
         return check, check.isChecked, lambda v, c=check: c.setChecked(bool(v))
      if kind in ("choice", "ref"):
         combo = QtWidgets.QComboBox()
         if kind == "choice":
            combo.addItems(f.get("choices") or [])
         else:
            combo.setEditable(True)   # a name the game does not have yet is allowed; the check says so
            combo.addItem(NO_REF)
            try:
               combo.addItems(self.data.names(f.get("kind", "")) if self.data is not None else [])
            except ENGINE_ERRORS as e:
               self.host.show_status(f"Plugin data: {e}")
         combo.activated.connect(lambda _i, k=key: self._field_changed(k))
         if combo.lineEdit() is not None:
            combo.lineEdit().editingFinished.connect(lambda k=key: self._field_changed(k))

         def get(c: QtWidgets.QComboBox = combo) -> Json:
            """!The chosen name (None for no reference)."""
            text = c.currentText()
            return None if text in (NO_REF, "") else text

         return combo, get, lambda v, c=combo: c.setCurrentText(NO_REF if v is None else str(v))
      if kind == "text":
         line = QtWidgets.QLineEdit()
         if f.get("max_length"):
            line.setMaxLength(f["max_length"])
         line.editingFinished.connect(lambda k=key: self._field_changed(k))
         return line, line.text, lambda v, e=line: e.setText("" if v is None else str(v))
      # lists, nested blocks and anything newer: JSON
      text = QtWidgets.QPlainTextEdit()
      text.setFixedHeight(text.fontMetrics().lineSpacing() * (JSON_LINES + 1))
      text.setPlaceholderText("JSON")
      apply = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+Return"), text)
      apply.activated.connect(lambda k=key: self._field_changed(k))

      def get_json(t: QtWidgets.QPlainTextEdit = text) -> Json:
         """!The parsed JSON (ValueError when it does not parse)."""
         return json.loads(t.toPlainText() or "null")

      wrapper = QtWidgets.QWidget()
      wl = QtWidgets.QVBoxLayout(wrapper)
      wl.setContentsMargins(0, 0, 0, 0)
      wl.addWidget(text)
      wl.addWidget(button("Apply", lambda k=key: self._field_changed(k), "Apply the JSON (Ctrl+Return)"))
      return wrapper, get_json, lambda v, t=text: t.setPlainText(json.dumps(v))

   def _field_changed(self, key: str) -> None:
      """!Writes one field into the record's block (one undo step).
      @param key  the field
      @return None
      """
      if self._filling or self.data is None:
         return
      pid, point, name = self.plugin_id(), self.point(), self.record()
      if None in (pid, point, name):
         self.explain("Set field", "record")
         return
      block = self.data.get(pid, point, name)
      if block is None:
         self.explain("Set field", "record with a block (Add block first)")
         return
      try:
         value = self._editors[key][1]()
      except ValueError as e:
         self.host.show_status(f"{key}: not JSON ({e})")
         return
      changed = dict(block)
      changed[key] = value
      if block.get(key) == value:
         return
      self._set(pid, point, name, changed)

   def _set(self, pid: str, point: str, name: str, block: Json) -> bool:
      """!Sets or removes a block through the host (one undo step).
      @param pid    the plugin
      @param point  the attach point
      @param name   the record
      @param block  the block, or None to remove it
      @return True when it went through
      """
      try:
         return self.data.set(pid, point, name, block, self.host.run_edit)
      except ENGINE_ERRORS as e:
         report_failure(self, "Plugin data", str(e))
         return False

   def add_block(self) -> bool:
      """!Gives the chosen record the plugin's block (its required fields; the rest show their defaults).
      @return True when added
      """
      pid, point, name = self.plugin_id(), self.point(), self.record()
      if self.data is None or None in (pid, point, name):
         return self.explain("Add block", "record")
      return self._set(pid, point, name, self.data.new_block(pid, point))

   def remove_block(self) -> bool:
      """!Removes the chosen record's block.
      @return True when removed
      """
      pid, point, name = self.plugin_id(), self.point(), self.record()
      if self.data is None or None in (pid, point, name):
         return self.explain("Remove block", "record")
      return self._set(pid, point, name, None)

   def _show_problems(self, block: Json) -> None:
      """!The record's problems: its schema's, then the connector's checks (references, validate hooks).
      @param block  the block shown, or None
      @return None
      """
      pid, point, name = self.plugin_id(), self.point(), self.record()
      lines: list[str] = []
      if block is not None and self.data is not None and None not in (pid, point, name):
         try:
            lines += [f"error: {m}" for m in self.data.problems(pid, point, block)]
            if not lines:
               lines += [f"{p.severity}: {p.message}" for p in self.data.check().problems
                         if p.plugin == pid and p.record == (point, name)]
         except ENGINE_ERRORS as e:
            lines.append(f"error: {e}")
      self.problems.setText("\n".join(lines) if lines else ("No problems" if block is not None else ""))

   def _show_preview(self) -> None:
      """!The chosen preview of the chosen record.
      @return None
      """
      reg = self._registry()
      pid, point, name = self.plugin_id(), self.point(), self.record()
      preview = reg.find("preview", self.preview_box.currentData()) if reg is not None else None
      text = ""
      if preview is None or self.data is None or None in (pid, point, name):
         text = "" if self.preview_box.count() else "The plugin has no preview"
      elif preview.attach_points and point not in preview.attach_points:
         text = f"{preview.title} does not show {point} records"
      else:
         try:
            block = self.data.get(pid, point, name)
            shown = self.data.complete(pid, point, block if block is not None else self.data.new_block(pid, point))
            text = preview.render(self.data, point, name, shown)
         except Exception as e:   # a plugin's preview must not break the panel
            text = f"the preview failed: {type(e).__name__}: {e}"
      self.preview.setPlainText(text)

   def refresh(self) -> None:
      """!Re-reads the records and the chosen one (after edits, undo and redo).
      @return None
      """
      if self.data is not None:
         self._fill_records()

   # -- files --------------------------------------------------------------------------------------------------------

   def _format(self, action: str) -> Any:
      """!The chosen file format.
      @param action  what was asked, for the message
      @return registry.FileFormat, or None (said in the status bar)
      """
      reg = self._registry()
      fmt = reg.find("format", self.format_box.currentData()) if reg is not None else None
      if fmt is None or self.data is None:
         self.explain(action, "file format")
      return fmt

   def export_file(self, path: str | Path | None = None) -> bool:
      """!Writes the plugin's blocks in the chosen format.
      @param path  the file, or None to ask
      @return True when written
      """
      fmt = self._format("Export")
      if fmt is None:
         return False
      if path is None:
         path, _f = QtWidgets.QFileDialog.getSaveFileName(self, "Export", "", f"{fmt.title} (*{fmt.suffix})")
         if not path:
            return False
      try:
         Path(path).write_text(self.data.export(fmt), encoding="utf-8")
      except (OSError, *ENGINE_ERRORS) as e:
         report_failure(self, "Export", str(e))
         return False
      self.host.show_status(f"Exported {Path(path).name}")
      return True

   def import_file(self, path: str | Path | None = None) -> bool:
      """!Reads a file of the chosen format into the plugin's blocks (one undo step over every file it changes).
      @param path  the file, or None to ask
      @return True when imported
      """
      fmt = self._format("Import")
      if fmt is None:
         return False
      if path is None:
         path, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Import", "", f"{fmt.title} (*{fmt.suffix})")
         if not path:
            return False
      try:
         changes = self.data.import_changes(fmt, Path(path).read_text(encoding="utf-8"))
         changed = self.data.apply(fmt.plugin, changes, f"Import {Path(path).name}")
      except (OSError, DocumentError, *ENGINE_ERRORS) as e:
         report_failure(self, "Import", str(e))
         return False
      self.host.show_status(f"Imported {Path(path).name}: {changed} record(s) changed")
      self.host.changed()
      return True
