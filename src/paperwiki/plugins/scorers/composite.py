"""Composite scorer — weighted multi-axis paper scoring.

The scorer fills :class:`paperwiki.core.models.ScoreBreakdown` with four
independent signals and aggregates them into a ``composite`` score via
the user-configurable weights:

================ ===========================================================
Axis             Heuristic
================ ===========================================================
``relevance``    Topic-keyword and category overlap with the paper.
``novelty``      Frequency of strong-innovation keywords in title/abstract.
``momentum``     Citation count if available, otherwise recency bonus.
``rigor``        Frequency of experiment/evaluation keywords in abstract.
================ ===========================================================

Each axis is normalized to ``[0, 1]``. ``composite`` is the dot product
of the axes with the configured weights (which must sum to 1).

This scorer is intentionally heuristic and string-based — production
scorers can subclass or replace it. The goal here is a sensible default
that any user can run without LLM calls or learned models.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from typing import TYPE_CHECKING

from paperwiki.core.models import (
    DEFAULT_SCORE_WEIGHTS,
    Recommendation,
    ScoreBreakdown,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from paperwiki.core.models import Paper, RunContext
    from paperwiki.plugins.filters.relevance import Topic


# Heuristic keyword sets used for the novelty and rigor axes. These are
# evaluated as word-boundary, case-insensitive matches.
_NOVELTY_KEYWORDS: frozenset[str] = frozenset(
    {
        "novel",
        "first",
        "new approach",
        "new method",
        "propose",
        "introduce",
        "state-of-the-art",
        "sota",
        "breakthrough",
        "surpass",
        "outperform",
        "pioneering",
    }
)

_RIGOR_KEYWORDS: frozenset[str] = frozenset(
    {
        "experiment",
        "evaluation",
        "benchmark",
        "ablation",
        "baseline",
        "comparison",
        "achieves",
        "improves",
    }
)


class CompositeScorer:
    """Score papers across four axes and aggregate via weighted sum."""

    name = "composite"

    def __init__(
        self,
        topics: list[Topic],
        *,
        weights: dict[str, float] | None = None,
        momentum_full_citations: int = 100,
        recency_full_days: int = 7,
    ) -> None:
        if not topics:
            msg = "CompositeScorer requires at least one topic"
            raise ValueError(msg)
        self.topics = list(topics)
        self.weights = dict(weights) if weights is not None else dict(DEFAULT_SCORE_WEIGHTS)
        self.momentum_full_citations = momentum_full_citations
        self.recency_full_days = recency_full_days

        # Validate weights once at construction by computing a probe
        # composite — surfaces "weights must sum to 1" early.
        ScoreBreakdown().compute_composite(self.weights)

        # Pre-compile keyword regex patterns once.
        self._topic_patterns: list[tuple[Topic, list[re.Pattern[str]]]] = []
        for topic in self.topics:
            patterns = [
                re.compile(rf"\b{re.escape(k)}\b", re.IGNORECASE) for k in topic.keyword_set
            ]
            self._topic_patterns.append((topic, patterns))
        self._novelty_patterns = [
            re.compile(rf"\b{re.escape(k)}\b", re.IGNORECASE) for k in _NOVELTY_KEYWORDS
        ]
        self._rigor_patterns = [
            re.compile(rf"\b{re.escape(k)}\b", re.IGNORECASE) for k in _RIGOR_KEYWORDS
        ]

    async def score(
        self,
        papers: AsyncIterator[Paper],
        ctx: RunContext,
    ) -> AsyncIterator[Recommendation]:
        async for paper in papers:
            relevance, matched_topics, topic_strengths = self._compute_relevance(paper)
            novelty = self._compute_novelty(paper)
            momentum = self._compute_momentum(paper, ctx)
            rigor = self._compute_rigor(paper)

            # Serialize per-topic strengths as a JSON string so the
            # ScoreBreakdown.notes dict stays ``dict[str, str]``.
            # Downstream consumers (MarkdownWikiBackend.upsert_paper) decode it.
            breakdown = ScoreBreakdown(
                relevance=relevance,
                novelty=novelty,
                momentum=momentum,
                rigor=rigor,
                notes={"topic_strengths": json.dumps(topic_strengths)},
            )
            breakdown.composite = breakdown.compute_composite(self.weights)

            ctx.increment("scorer.composite.scored")
            yield Recommendation(
                paper=paper,
                score=breakdown,
                matched_topics=matched_topics,
            )

    # ------------------------------------------------------------------
    # Axis implementations
    # ------------------------------------------------------------------

    def _compute_relevance(self, paper: Paper) -> tuple[float, list[str], dict[str, float]]:
        haystack = f"{paper.title}\n{paper.abstract}".lower()
        paper_categories = {c.lower() for c in paper.categories}

        matched_topics: list[str] = []
        topic_strengths: dict[str, float] = {}
        total_hits = 0
        for topic, patterns in self._topic_patterns:
            topic_hits = 0
            if topic.category_set & paper_categories:
                total_hits += 1
                topic_hits += 1
            keyword_hits = sum(1 for p in patterns if p.search(haystack))
            if keyword_hits:
                total_hits += keyword_hits
                topic_hits += keyword_hits
            # Per-topic strength uses the same saturating curve as the
            # aggregate; single hit for a single-keyword topic scores 0.5
            # (above default threshold of 0.3).
            if topic_hits > 0:
                strength = min(1.0 - 0.5**topic_hits, 1.0)
                matched_topics.append(topic.name)
            else:
                strength = 0.0
            topic_strengths[topic.name] = round(strength, 4)

        if total_hits == 0:
            return 0.0, [], topic_strengths

        # Saturating curve: each hit contributes diminishing returns up to 1.0.
        # Three hits reach ~0.75; six hits reach ~0.94.
        score = 1.0 - 0.5**total_hits
        return min(score, 1.0), matched_topics, topic_strengths

    def _compute_novelty(self, paper: Paper) -> float:
        haystack = f"{paper.title}\n{paper.abstract}".lower()
        hits = sum(1 for p in self._novelty_patterns if p.search(haystack))
        if hits == 0:
            return 0.0
        # 1 hit -> 0.5, 2 hits -> 0.75, 3+ hits -> 0.875+
        return min(1.0 - 0.5**hits, 1.0)

    def _compute_momentum(self, paper: Paper, ctx: RunContext) -> float:
        if paper.citation_count is not None and paper.citation_count > 0:
            ratio = paper.citation_count / self.momentum_full_citations
            return min(max(ratio, 0.0), 1.0)
        # No citation data — fall back to a recency bonus so brand-new
        # papers still get a momentum signal.
        if self.recency_full_days <= 0:
            return 0.0
        delta = ctx.target_date - paper.published_at
        # Within recency_full_days -> 1.0 - 0.0; older -> linearly down to 0
        # over a 30-day window.
        if delta <= timedelta(days=self.recency_full_days):
            return 0.5
        decay_window = timedelta(days=30)
        decay = max(0.0, 1.0 - (delta - timedelta(days=self.recency_full_days)) / decay_window)
        return min(max(0.5 * decay, 0.0), 1.0)

    def _compute_rigor(self, paper: Paper) -> float:
        haystack = paper.abstract.lower()
        hits = sum(1 for p in self._rigor_patterns if p.search(haystack))
        if hits == 0:
            return 0.0
        return min(1.0 - 0.5**hits, 1.0)


__all__ = ["CompositeScorer"]
