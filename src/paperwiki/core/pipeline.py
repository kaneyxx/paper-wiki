"""Pipeline orchestrator for paper-wiki.

The :class:`Pipeline` chains the four async stages — sources, filters,
scorer, reporters — and an optional :class:`~paperwiki.core.protocols.WikiBackend`
into a single ``run`` coroutine. The orchestration logic lives entirely
here so individual plugins stay focused on their stage.

The current implementation:

* fans in sources sequentially (one source drained before the next),
* isolates per-source ``IntegrationError``s so one rate-limited or
  flaky source does not abort the whole digest,
* chains filters in declaration order,
* delegates scoring to a single scorer,
* sorts the resulting :class:`Recommendation` list by ``score.composite``
  (descending),
* applies an optional ``top_k`` truncation,
* fans out to all reporters concurrently via :func:`asyncio.gather`,
* and, if a ``wiki`` backend was provided, upserts each recommendation.

Concurrent source fan-in is a Phase 2 optimization once real network
plugins land — it is intentionally simple here so the orchestration
contract stays easy to reason about.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

from paperwiki.core.errors import IntegrationError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from paperwiki.core.models import Paper, Recommendation, RunContext
    from paperwiki.core.protocols import (
        Filter,
        Reporter,
        Scorer,
        Source,
        WikiBackend,
    )


@dataclass(slots=True)
class PipelineResult:
    """The outcome of a single :meth:`Pipeline.run`.

    ``recommendations`` is the (top-k truncated) sorted list emitted to
    every reporter. ``counters`` is a snapshot of the run context's
    counter dict at run completion.
    """

    recommendations: list[Recommendation]
    counters: dict[str, int]


class Pipeline:
    """Composes source → filters → scorer → reporters into one async run.

    Construction validates that at least one source and one reporter are
    provided; an empty pipeline is a configuration error, not a no-op.
    """

    def __init__(
        self,
        sources: list[Source],
        filters: list[Filter],
        scorer: Scorer,
        reporters: list[Reporter],
        wiki: WikiBackend | None = None,
    ) -> None:
        if not sources:
            msg = "Pipeline requires at least one source"
            raise ValueError(msg)
        if not reporters:
            msg = "Pipeline requires at least one reporter"
            raise ValueError(msg)
        self.sources = sources
        self.filters = filters
        self.scorer = scorer
        self.reporters = reporters
        self.wiki = wiki

    async def run(self, ctx: RunContext, top_k: int | None = None) -> PipelineResult:
        """Execute the pipeline, returning a :class:`PipelineResult`.

        The optional ``top_k`` truncates the sorted recommendation list
        before reporters are invoked.
        """
        # 1. Source fan-in (sequential for now).
        paper_stream = self._merge_sources(ctx)

        # 2. Filter chain.
        for stage in self.filters:
            paper_stream = stage.apply(paper_stream, ctx)

        # 3. Scoring.
        rec_stream = self.scorer.score(paper_stream, ctx)

        # 4. Top-K selection.
        recs: list[Recommendation] = [rec async for rec in rec_stream]
        recs.sort(key=lambda r: r.score.composite, reverse=True)
        if top_k is not None:
            recs = recs[:top_k]

        # 5. Reporter fan-out (concurrent).
        if recs or self.reporters:
            await asyncio.gather(*(r.emit(recs, ctx) for r in self.reporters))

        # 6. Optional wiki upsert (concurrent).
        if self.wiki is not None and recs:
            await asyncio.gather(*(self.wiki.upsert_paper(r) for r in recs))

        return PipelineResult(recommendations=recs, counters=dict(ctx.counters))

    async def _merge_sources(self, ctx: RunContext) -> AsyncIterator[Paper]:
        """Yield papers from every source in declaration order.

        Each fetched paper increments ``source.<name>.fetched`` on the run
        context. ``IntegrationError`` from a single source (network
        timeout, 429, 503, etc.) is caught and counted as
        ``source.<name>.errors`` rather than aborting the whole run —
        a digest with three sources should still emit a useful result
        when one source is down.
        """
        for src in self.sources:
            try:
                async for paper in src.fetch(ctx):
                    ctx.increment(f"source.{src.name}.fetched")
                    yield paper
            except IntegrationError as exc:
                ctx.increment(f"source.{src.name}.errors")
                logger.warning(
                    "pipeline.source.failed",
                    source=src.name,
                    error=str(exc),
                )


__all__ = [
    "Pipeline",
    "PipelineResult",
]
