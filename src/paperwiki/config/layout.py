"""Default vault subdirectory names used by reporters and runners.

The defaults here are deliberately friendly (no numeric prefixes) so
paper-wiki does not impose a personal-knowledge-management convention
(Johnny.Decimal, PARA) on users who do not use one. Users who do can
override every subdir per-recipe — see ``recipes/README.md`` for
examples.

Why three constants and not three reporter / runner default arguments?

* Single source of truth across reporters, the wiki backend, and the
  diagnostics runner.
* Makes a recipe author's "I want PARA-style numbers" override one
  edit per recipe instead of three.
* Simplifies migration: changing a default later only touches this
  module.
"""

from __future__ import annotations

DAILY_SUBDIR = "Daily"
SOURCES_SUBDIR = "Sources"
WIKI_SUBDIR = "Wiki"

__all__ = [
    "DAILY_SUBDIR",
    "SOURCES_SUBDIR",
    "WIKI_SUBDIR",
]
