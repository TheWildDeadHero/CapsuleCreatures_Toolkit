"""!Work that runs on another thread while the editor stays usable (I2: a whole-world compile of a large world).

A job is a callable without arguments that touches no Qt object and no Document (core.world.Project.snapshot()
copies what it needs first). Its result comes back on the GUI thread: a timer of the owner widget polls the
thread, so the callback runs where widgets may be changed. A newer job of the same owner and name replaces the
older one's callback (its result is dropped).
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from PySide6 import QtCore, QtWidgets

## Milliseconds between looks at a running job.
POLL_MS = 100


class Job:
   """!One job on its thread, with the callback that takes its result."""

   def __init__(self, work: Callable[[], Any], done: Callable[[Any], None]) -> None:
      """!Starts the job.
      @param work  callable() -> result, run on the thread
      @param done  callable(result), run on the GUI thread when the job is over
      """
      ## The callback; None once dropped.
      self.done: Callable[[Any], None] | None = done
      ## The result, once there is one.
      self.result = None
      ## The thread (a daemon: closing the editor does not wait for it).
      self.thread = threading.Thread(target=self._run, args=(work,), daemon=True)
      self.thread.start()

   def _run(self, work: Callable[[], Any]) -> None:
      """!Runs the work and keeps its result.
      @param work  the callable
      @return None
      """
      self.result = work()


def start(owner: QtWidgets.QWidget, name: str, work: Callable[[], Any], done: Callable[[Any], None]) -> Job:
   """!Runs a job on its own thread; done(result) runs on the GUI thread afterwards (while owner lives).
   @param owner  widget the polling timer belongs to
   @param name   the job's name: a newer job of the same name drops the older one's callback
   @param work   callable() -> result (no Qt objects, no Documents)
   @param done   callable(result)
   @return the Job
   """
   jobs: dict[str, Job] | None = getattr(owner, "_background_jobs", None)
   if jobs is None:
      jobs = {}
      setattr(owner, "_background_jobs", jobs)
   old = jobs.get(name)
   if old is not None:
      old.done = None
   job = Job(work, done)
   jobs[name] = job
   timer = QtCore.QTimer(owner)
   timer.setInterval(POLL_MS)

   def poll() -> None:
      """!Hands the result over once the thread is done."""
      if job.thread.is_alive():
         return
      timer.stop()
      timer.deleteLater()
      if jobs.get(name) is job:
         del jobs[name]
      if job.done is not None:
         job.done(job.result)
   timer.timeout.connect(poll)
   timer.start()
   return job


def running(owner: QtWidgets.QWidget, name: str) -> bool:
   """!Whether a job of that name is still running for the owner.
   @param owner  widget
   @param name   job name
   @return True while it runs
   """
   job = (getattr(owner, "_background_jobs", None) or {}).get(name)
   return job is not None and job.thread.is_alive()
