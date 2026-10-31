"""!The view of a map that map tools and overlays work on (no user interface)."""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
   from ..core.document import Document
   from ..core.world import Project

## A host's run_edit: callable(label, fn, document) -> True when the edit went through.
RunEdit = Callable[[str, Callable[[], object], "Document"], bool]


class MapView:
   """!A map of a project, plus the way to change it."""

   def __init__(self, project: Project | None, map_name: str, run_edit: RunEdit | None = None,
                status: Callable[[str], object] | None = None) -> None:
      """!Wraps a map.
      @param project   core.world.Project
      @param map_name  map name
      @param run_edit  callable(label, fn, document) -> bool (a host's run_edit), or None to edit directly
      @param status    callable(text) for short messages, or None
      """
      ## The core.world.Project.
      self.project = project
      ## The map shown.
      self.map_name = map_name
      ## The host's run_edit, or None (edits go to the Document directly).
      self._run_edit = run_edit
      ## The host's status line, or None.
      self._status = status

   @property
   def doc(self) -> Document | None:
      """!The map's Document, or None.
      @return Document, or None when there is no project or no such map
      """
      if self.project is None or self.map_name not in self.project.map_names():
         return None
      return self.project.map(self.map_name)

   def edit(self, label: str, fn: Callable[[], object], document: Document | None = None) -> bool:
      """!Runs a change as one document command.
      @param label     undo label
      @param fn        callable doing the change
      @param document  Document it changes (default: the map's)
      @return True when it went through
      """
      doc = document or self.doc
      if doc is None:
         return False
      if self._run_edit is not None:
         return self._run_edit(label, fn, doc)
      with doc.edit(label):
         fn()
      return True

   def status(self, text: str) -> None:
      """!Shows a short message (the host's status bar, or nothing).
      @param text  message
      @return None
      """
      if self._status is not None:
         self._status(text)
