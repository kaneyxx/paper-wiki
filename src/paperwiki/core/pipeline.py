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

Progress reporting (task 9.166) — every stage emits a structured
``loguru`` start/complete pair so runners and SKILLs can show real-time
progress. The stage names are stable contract surface keyed off by
9.167's ``run-status.jsonl`` ledger:

* ``source.fetch.start`` / ``source.fetch.complete``
* ``filter.<name>.start`` / ``filter.<name>.complete``
* ``scorer.start`` / ``scorer.complete``
* ``report.write.start`` / ``report.write.complete``

Each ``*.complete`` line carries ``elapsed_ms: int`` plus stage-specific
counts (``papers_in`` / ``papers_out`` / ``papers_scored`` /
``reporters`` / ``recommendations``).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

from paperwiki.core.errors import IntegrationError

if TYPE_CHECKING:
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


def _elapsed_ms(start_ns: int) -> int:
    """Return milliseconds elapsed since a ``time.perf_counter_ns()`` mark."""
    return (time.perf_counter_ns() - start_ns) // 1_000_000


async def _aiter(items: list[Paper]) -> AsyncIterator[Paper]:
    """Wrap a materialised list in an async iterator for filter/scorer feed."""
    for item in items:
        yield item


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
        # 1. Source fan-in (sequential for now). Eagerly drain so we can
        #    log per-source counts and total elapsed time before handing
        #    off to filters. The per-source breakdown is logged inside
        #    ``_drain_sources``; the second tuple element is returned for
        #    test-time inspection only.
        papers, _per_source = await self._drain_sources(ctx)

        # 2. Filter chain — log per-stage start/complete with papers_in
        #    and papers_out so observers can see drop rates per filter.
        current = papers
        for stage in self.filters:
            current = await self._run_filter(stage, current, ctx)

        # 3. Scoring.
        recs = await self._run_scorer(current, ctx)

        # 4. Top-K selection (no logging — this is a pure sort/slice).
        recs.sort(key=lambda r: r.score.composite, reverse=True)
        if top_k is not None:
            recs = recs[:top_k]

        # 5. Reporter fan-out (concurrent).
        await self._run_reporters(recs, ctx)

        # 6. Optional wiki upsert (concurrent). Wiki upserts are not
        #    tracked as a pipeline progress stage in v0.4.x because the
        #    backend writes are content-addressable and out-of-band from
        #    the digest contract.
        if self.wiki is not None and recs:
            await asyncio.gather(*(self.wiki.upsert_paper(r) for r in recs))

        return PipelineResult(recommendations=recs, counters=dict(ctx.counters))

    async def _drain_sources(self, ctx: RunContext) -> tuple[list[Paper], dict[str, int]]:
        """Drain every source, returning the merged paper list + per-source counts.

        Each fetched paper increments ``source.<name>.fetched`` on the run
        context. ``IntegrationError`` from a single source (network
        timeout, 429, 503, etc.) is caught and counted as
        ``source.<name>.errors`` rather than aborting the whole run —
        a digest with three sources should still emit a useful result
        when one source is down.
        """
        start_ns = time.perf_counter_ns()
        logger.info(
            "source.fetch.start",
            sources=[src.name for src in self.sources],
        )

        papers: list[Paper] = []
        per_source: dict[str, int] = {}
        for src in self.sources:
            count = 0
            try:
                async for paper in src.fetch(ctx):
                    ctx.increment(f"source.{src.name}.fetched")
                    papers.append(paper)
                    count += 1
            except IntegrationError as exc:
                ctx.increment(f"source.{src.name}.errors")
                logger.warning(
                    "pipeline.source.failed",
                    source=src.name,
                    error=str(exc),
                )
            per_source[src.name] = count

        logger.info(
            "source.fetch.complete",
            papers_out=len(papers),
            per_source=per_source,
            elapsed_ms=_elapsed_ms(start_ns),
        )
        return papers, per_source

    async def _run_filter(
        self, stage: Filter, papers_in: list[Paper], ctx: RunContext
    ) -> list[Paper]:
        """Run a single filter with start/complete progress logging.

        ``papers_in`` is materialised so we can log the count up-front;
        the filter's ``apply`` is consumed eagerly into ``papers_out``
        so the complete-line gets an accurate drop count.
        """
        start_ns = time.perf_counter_ns()
        logger.info(
            f"filter.{stage.name}.start",
            papers_in=len(papers_in),
        )
        stream = stage.apply(_aiter(papers_in), ctx)
        papers_out: list[Paper] = [p async for p in stream]
        logger.info(
            f"filter.{stage.name}.complete",
            papers_in=len(papers_in),
            papers_out=len(papers_out),
            elapsed_ms=_elapsed_ms(start_ns),
        )
        return papers_out

    async def _run_scorer(self, papers: list[Paper], ctx: RunContext) -> list[Recommendation]:
        """Run the scorer with start/complete progress logging."""
        start_ns = time.perf_counter_ns()
        logger.info(
            "scorer.start",
            scorer=self.scorer.name,
            papers_in=len(papers),
        )
        rec_stream = self.scorer.score(_aiter(papers), ctx)
        recs: list[Recommendation] = [rec async for rec in rec_stream]
        logger.info(
            "scorer.complete",
            scorer=self.scorer.name,
            papers_scored=len(recs),
            elapsed_ms=_elapsed_ms(start_ns),
        )
        return recs

    async def _run_reporters(self, recs: list[Recommendation], ctx: RunContext) -> None:
        """Fan out to every reporter concurrently with start/complete logging.

        Reporters always run (even on an empty ``recs`` list) so they can
        write a "no recommendations today" digest file — that is part of
        the existing reporter contract.
        """
        start_ns = time.perf_counter_ns()
        logger.info(
            "report.write.start",
            reporters=len(self.reporters),
            recommendations=len(recs),
        )
        if recs or self.reporters:
            await asyncio.gather(*(r.emit(recs, ctx) for r in self.reporters))
        logger.info(
            "report.write.complete",
            reporters=len(self.reporters),
            recommendations=len(recs),
            elapsed_ms=_elapsed_ms(start_ns),
        )


__all__ = [
    "Pipeline",
    "PipelineResult",
]
