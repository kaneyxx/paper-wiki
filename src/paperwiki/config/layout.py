"""Default vault subdirectory names used by reporters and runners.

The defaults here are deliberately friendly (no numeric prefixes) so
paper-wiki does not impose a personal-knowledge-management convention
(Johnny.Decimal, PARA) on users who do not use one. Users who do can
override every subdir per-recipe — see ``recipes/README.md`` for
examples.

Why one module of constants and not three reporter / runner default
arguments?

* Single source of truth across reporters, the wiki backend, runners,
  and the diagnostics output.
* Makes a recipe author's "I want PARA-style numbers" override one
  edit per recipe instead of N.
* Simplifies migration: changing a default later only touches this
  module.

Task 9.184 (D-T + D-Z) follow-ups:

* ``PAPERS_SUBDIR = "papers"`` — canonical v0.4.x typed-subdir name
  for per-paper notes (was ``Wiki/sources/`` in v0.3.x).
* ``LEGACY_PAPERS_SUBDIR = "sources"`` — read-only back-compat name
  scheduled for deletion in v0.5.0. Every read-fallback shim in the
  codebase imports this single name so the v0.5.0 cleanup window is
  grep-able.
* ``CONCEPTS_SUBDIR = "concepts"`` — typed-subdir for synthesized
  concept articles. Backend used to declare its own
  ``_CONCEPTS_DIRNAME = "concepts"`` constant; D-Z folds it into this
  module so any future relocation is one line.
* ``SOURCES_SUBDIR`` (vault-root ``Sources/``) was deleted in 9.184.
  Q1 ratified — verified on the maintainer's vault that no runner
  ever wrote to it.
"""

from __future__ import annotations

DAILY_SUBDIR = "Daily"
PAPERS_SUBDIR = "papers"
LEGACY_PAPERS_SUBDIR = "sources"  # v0.5.0: delete this constant.
CONCEPTS_SUBDIR = "concepts"
WIKI_SUBDIR = "Wiki"

__all__ = [
    "CONCEPTS_SUBDIR",
    "DAILY_SUBDIR",
    "LEGACY_PAPERS_SUBDIR",
    "PAPERS_SUBDIR",
    "WIKI_SUBDIR",
]
