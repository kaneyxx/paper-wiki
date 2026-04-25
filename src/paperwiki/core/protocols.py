"""Plugin protocols for the paper-wiki pipeline.

Every pipeline stage is described by a runtime-checkable
:class:`typing.Protocol`. Plugin authors implement these by writing a
class that exposes the required attributes — they do not need to inherit
from any base class. The protocols are deliberately small and async-first
to match the I/O-bound nature of fetching, filtering, scoring, and
reporting on papers.

.. note::

    All protocols in this module are **@experimental** until
    paper-wiki v1.0. The shapes may change in minor versions before then.
    Plugin authors should pin to a specific paper-wiki release.

The four pipeline stages compose into:

.. code-block::

    Source -> Filter -> Scorer -> Reporter

with an optional :class:`WikiBackend` for cross-paper persistence.

Runtime ``isinstance`` checks only verify attribute *presence*, not
signature compatibility — Python does not enforce Protocol method
signatures at runtime. Static signature checking happens via mypy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from paperwiki.core.models import Paper, Recommendation, RunContext


@runtime_checkable
class Source(Protocol):
    """Yields candidate :class:`Paper` objects from an external system."""

    name: str

    def fetch(self, ctx: RunContext) -> AsyncIterator[Paper]:
        """Return an async iterator of papers for the given run context."""
        ...


@runtime_checkable
class Filter(Protocol):
    """Drops or transforms papers based on a predicate.

    A filter is given an async stream of papers and yields a (potentially
    smaller) async stream. Filters MUST be referentially transparent
    within a single pipeline run.
    """

    name: str

    def apply(self, papers: AsyncIterator[Paper], ctx: RunContext) -> AsyncIterator[Paper]:
        """Return a filtered async iterator of papers."""
        ...


@runtime_checkable
class Scorer(Protocol):
    """Assigns a :class:`ScoreBreakdown` to each paper, producing recommendations."""

    name: str

    def score(self, papers: AsyncIterator[Paper], ctx: RunContext) -> AsyncIterator[Recommendation]:
        """Return an async iterator of recommendations."""
        ...


@runtime_checkable
class Reporter(Protocol):
    """Persists a list of recommendations to a target sink (file, vault, API)."""

    name: str

    async def emit(self, recs: list[Recommendation], ctx: RunContext) -> None:
        """Write the recommendations to the reporter's sink."""
        ...


@runtime_checkable
class WikiBackend(Protocol):
    """Optional knowledge-base read/write for cross-paper queries.

    Unlike the other protocols, ``WikiBackend`` does not expose a ``name``
    attribute — backends are referenced by config rather than by a
    plugin-registry key, so the registry naming convention does not
    apply.
    """

    async def upsert_paper(self, rec: Recommendation) -> None:
        """Insert or update the wiki entry for the given recommendation."""
        ...

    async def query(self, q: str) -> list[Recommendation]:
        """Return recommendations matching the keyword query ``q``."""
        ...


__all__ = [
    "Filter",
    "Reporter",
    "Scorer",
    "Source",
    "WikiBackend",
]
