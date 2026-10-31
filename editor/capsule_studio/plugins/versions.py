"""!Calendar versions and deprecations (D-10 §3).

A version is YYYY.MM.DD.MMMM: the UTC date and the minutes since 00:00 UTC
(0000-1439), always zero-padded, so versions sort the same as numbers and
as text. Deprecated items keep working for 6 months, counted on version
dates (never the clock), then they are removed.
"""
from __future__ import annotations

import calendar
import functools
import re
import warnings
from collections.abc import Callable
from typing import ParamSpec, TypeVar

## A valid calendar version.
PATTERN = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})\.(\d{4})")
## Months a deprecated item keeps working.
DEPRECATION_MONTHS = 6
## Months in a year.
MONTHS_PER_YEAR = 12
## Last minute of a UTC day (23:59 is minute 1439).
LAST_MINUTE_OF_DAY = 1439
## Length of the date part "YYYY.MM.DD" of a version.
DATE_TEXT_LENGTH = 10
## Match group of a requirement clause holding the version (group 1 is the operator).
CLAUSE_VERSION_GROUP = 2
## warnings.warn() stack level naming the deprecated function's caller.
CALLER_STACK_LEVEL = 2

## Parameters of a deprecated function.
Params = ParamSpec("Params")
## Return type of a deprecated function.
Result = TypeVar("Result")


class VersionError(ValueError):
   """!A version or requirement is malformed."""
   pass


class PluginDeprecationWarning(UserWarning):
   """!A deprecated plugin API item was used (shown once per call site)."""
   pass


def parse(text: object) -> tuple[int, int, int, int]:
   """!Checks and splits a calendar version.
   @param text  "2026.10.17.0690"
   @return (year, month, day, minutes)
   @throws VersionError when it is not zero-padded YYYY.MM.DD.MMMM or not a real date and minute
   """
   m = PATTERN.fullmatch(text) if isinstance(text, str) else None
   if m is None:
      raise VersionError(f"version {text!r} must be zero-padded YYYY.MM.DD.MMMM (UTC date, minutes since 00:00)")
   y, mo, d, mins = (int(g) for g in m.groups())
   if not 1 <= mo <= MONTHS_PER_YEAR or not 1 <= d <= calendar.monthrange(y, mo)[1] or mins > LAST_MINUTE_OF_DAY:
      raise VersionError(f"version {text!r} is not a real UTC date and minute")
   return y, mo, d, mins


def satisfies(version: str, requirement: str) -> bool:
   """!Whether a version meets a requirement.
   @param version      calendar version
   @param requirement  comma-separated clauses, each an operator (>=, >, <=, <, ==) and a version,
                       e.g. ">=2026.10.01.0000, <2027.01.01.0000"
   @return bool
   """
   v = parse(version)
   for clause in requirement.split(","):
      m = re.fullmatch(r"\s*(>=|<=|==|>|<)\s*(\S+)\s*", clause)
      if m is None:
         raise VersionError(f"requirement {requirement!r}: each clause is an operator and a version")
      op, other = m.group(1), parse(m.group(CLAUSE_VERSION_GROUP))
      ok = {">=": v >= other, "<=": v <= other, "==": v == other, ">": v > other, "<": v < other}[op]
      if not ok:
         return False
   return True


def removable_from(deprecated_in: str) -> str:
   """!The first version date at which a deprecated item may be removed.
   @param deprecated_in  calendar version of the release that deprecated it
   @return "YYYY.MM.DD" (same day 6 months later, or that month's last day)
   """
   y, mo, d, _ = parse(deprecated_in)
   mo += DEPRECATION_MONTHS
   # Months counted from 0 carry whole years over; then back to 1-12.
   y, mo = y + (mo - 1) // MONTHS_PER_YEAR, (mo - 1) % MONTHS_PER_YEAR + 1
   d = min(d, calendar.monthrange(y, mo)[1])
   return f"{y:04d}.{mo:02d}.{d:02d}"


def may_remove(deprecated_in: str, release: str) -> bool:
   """!Whether a release may remove an item deprecated in another.
   @param deprecated_in  version that deprecated it
   @param release        version of the release
   @return bool
   """
   # Zero-padded dates compare correctly as text.
   return release[:DATE_TEXT_LENGTH] >= removable_from(deprecated_in)


def deprecated(since: str, use: str) -> Callable[[Callable[Params, Result]], Callable[Params, Result]]:
   """!Marks a plugin API function deprecated: each call site warns once,
   naming the replacement and the removal date.
   @param since  calendar version that deprecates it
   @param use    what to use instead
   @return decorator
   """
   parse(since)

   def wrap(fn: Callable[Params, Result]) -> Callable[Params, Result]:
      @functools.wraps(fn)
      def inner(*args: Params.args, **kwargs: Params.kwargs) -> Result:
         warnings.warn(f"{fn.__name__} is deprecated since {since}: use {use} (removed from {removable_from(since)})",
                       PluginDeprecationWarning, stacklevel=CALLER_STACK_LEVEL)
         return fn(*args, **kwargs)
      inner.deprecated = (since, use)
      return inner
   return wrap
