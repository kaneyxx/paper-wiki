"""D-S regression baseline for the v0.4.0 digest pipeline.

Per **decision D-S** (consensus plan §3 Round 3), the only show-stopper
for shipping v0.4.0 is **digest output-quality regression**. Specifically:

* source coverage drop
* filter false-negatives (otherwise-relevant papers being dropped)
* scorer top-K ranking degradation

Migration loss, Obsidian indexing changes, and performance cliffs are
patchable, NOT rollback-class — they get a follow-up release rather
than the whole v0.4.x branch reverted.

D-S also refines the contract to **exclude dedup-ledger drops from the
comparison** (consensus plan iter-2 R10): "fewer papers" via the new
9.168 dedup ledger is *intended* behavior, not regression. The
synthetic source here generates fresh ids on each run so the dedup
ledger is always empty for the comparison.

This module is the deterministic synthetic baseline. The pre-tag
manual D-S check (real ``daily-arxiv`` recipe against arXiv's live API)
is documented in :file:`references/release-process.md` and is the
caller's responsibility before pushing the v0.4.0 tag — what we lock
in here is the **synthetic-fixture** invariant so any future change
that drops fixture coverage / pass-rate / top-K relevance fails CI.

Snapshot rationale: the numbers below are derived from running the
full v0.4.0 candidate pipeline (commit 92eebd1) on the 50-paper
fixture. Future contributors who change the scorer / filters / sort
order should update the snapshot ONLY if the change is intentional
and the user accepts the new behavior.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Pre-existing circular-import workaround. Loading paperwiki.config.recipe
# *before* paperwiki.plugins.reporters lets recipe.py finish initialising
# (it imports ObsidianReporter eagerly), so the later
# ``from paperwiki.plugins.reporters import ...`` line below sees an already-
# loaded module rather than racing on the half-loaded one. Tests collected
# alphabetically before this file (e.g. test_end_to_end_digest) trigger the
# same import order via collection order; doing it explicitly here makes
# the order independent of pytest collection.
import paperwiki.config.recipe  # noqa: F401 — import-order workaround
from paperwiki.core.models import Author, Paper, RunContext
from paperwiki.core.pipeline import Pipeline
from paperwiki.plugins.filters import (
    DedupFilter,
    MarkdownVaultKeyLoader,
    RecencyFilter,
    RelevanceFilter,
    Topic,
)
from paperwiki.plugins.reporters import MarkdownReporter
from paperwiki.plugins.scorers import CompositeScorer

# ---------------------------------------------------------------------------
# Deterministic 50-paper synthetic fixture
# ---------------------------------------------------------------------------
#
# Mirrors the daily-arxiv recipe shape (vlm + agents topics, 7-day
# recency window). 30 in-window relevant papers + 10 out-of-window
# (RecencyFilter drops) + 10 in-window but irrelevant (RelevanceFilter
# drops). Matches the daily-arxiv recipe well enough that the synthetic
# pass-rate is a meaningful proxy for the live-feed pass-rate.
#
# Paper ids are deterministic, so the test gives identical output on
# every run. Citation counts spread across 0-200 so the scorer's
# momentum axis has a meaningful spread.

_TARGET = datetime(2026, 4, 25, tzinfo=UTC)


def _paper(
    *,
    n: int,
    title: str,
    abstract: str,
    days_old: int,
    categories: list[str],
    citations: int,
) -> Paper:
    return Paper(
        canonical_id=f"arxiv:2604.{n:05d}",
        title=title,
        authors=[Author(name=f"Author {n}")],
        abstract=abstract,
        published_at=_TARGET - timedelta(days=days_old),
        categories=categories,
        citation_count=citations,
    )


def _build_fixture_papers() -> list[Paper]:
    """50 deterministic papers - 30 keepers, 20 expected drops."""
    # 15 in-window vision-language keepers (recency<=7, relevance match).
    vlm_keepers = [
        _paper(
            n=1000 + i,
            title=f"Vision-Language Paper #{i}",
            abstract=(
                f"We propose a new vision-language model #{i} for"
                " multimodal reasoning. Foundation model approach."
            ),
            days_old=(i % 6) + 1,  # 1..6 days old
            categories=["cs.CV", "cs.LG"],
            citations=10 + (i * 7),
        )
        for i in range(15)
    ]
    # 15 in-window agents keepers (recency<=7, relevance match).
    agent_keepers = [
        _paper(
            n=2000 + i,
            title=f"Agent Reasoning Paper #{i}",
            abstract=(
                f"Agent #{i} performs tool use and reasoning on"
                " complex tasks via foundation model orchestration."
            ),
            days_old=(i % 6) + 1,
            categories=["cs.AI", "cs.MA"],
            citations=5 + (i * 11),
        )
        for i in range(15)
    ]
    # 10 out-of-window relevant papers (RecencyFilter must drop).
    out_of_window = [
        _paper(
            n=3000 + i,
            title=f"Old Foundation Model #{i}",
            abstract=f"An older vision-language paper #{i}.",
            days_old=30 + i,  # 30..39 days old
            categories=["cs.CV"],
            citations=50,
        )
        for i in range(10)
    ]
    # 10 in-window irrelevant papers (RelevanceFilter must drop).
    irrelevant = [
        _paper(
            n=4000 + i,
            title=f"Quantum Field Theory Paper #{i}",
            abstract=f"A study of quantum chromodynamics #{i}.",
            days_old=(i % 6) + 1,
            categories=["hep-th"],
            citations=2,
        )
        for i in range(10)
    ]
    return [*vlm_keepers, *agent_keepers, *out_of_window, *irrelevant]


class _StaticSource:
    name = "arxiv"  # match the production source name so counters key correctly

    def __init__(self, papers: list[Paper]) -> None:
        self._papers = papers

    async def fetch(self, ctx: RunContext) -> AsyncIterator[Paper]:
        for paper in self._papers:
            yield paper


# ---------------------------------------------------------------------------
# Snapshot baseline (locked in commit 92eebd1, 2026-05-01)
# ---------------------------------------------------------------------------

# Total papers fed in.
_EXPECTED_SOURCE_FETCHED = 50

# RecencyFilter drops: the 10 out-of-window papers.
_EXPECTED_RECENCY_DROPPED = 10

# RelevanceFilter drops: the 10 irrelevant + plus any out-of-window
# that survived recency (none — recency runs first).
_EXPECTED_RELEVANCE_DROPPED = 10

# DedupFilter drops: 0, since the fixture vault is empty (D-S
# explicitly excludes dedup drops).
_EXPECTED_DEDUP_DROPPED = 0

# After all filters: 30 papers (15 vlm + 15 agents) survive.
_EXPECTED_SCORER_SCORED = 30

# Top-K=10 — exact id ordering is locked in for the v0.4.0 candidate.
# The CompositeScorer combines relevance * novelty * momentum * rigor;
# vlm papers come out ahead in this fixture because their abstracts hit
# more keyword variants ("vision-language", "vision-language model",
# "multimodal", "foundation model" — 4 keyword overlaps) than the
# agents abstracts ("agent", "tool use", "reasoning" — 3 overlaps), so
# vlm's relevance axis dominates the citation-driven momentum axis.
#
# Snapshot captured from commit 92eebd1 / 2026-05-01. Update only when
# the user explicitly accepts a new ranking.
_EXPECTED_TOP_10_IDS = [
    "arxiv:2604.01013",  # vlm   #13
    "arxiv:2604.01014",  # vlm   #14
    "arxiv:2604.01012",  # vlm   #12
    "arxiv:2604.01011",  # vlm   #11
    "arxiv:2604.01010",  # vlm   #10
    "arxiv:2604.01009",  # vlm   #9
    "arxiv:2604.02009",  # agent #9
    "arxiv:2604.02010",  # agent #10
    "arxiv:2604.02011",  # agent #11
    "arxiv:2604.02012",  # agent #12
]


def _make_pipeline(vault: Path, output_dir: Path) -> Pipeline:
    topics = [
        Topic(
            name="vision-language",
            keywords=["vision-language", "vision language model", "multimodal", "foundation model"],
            categories=["cs.CV", "cs.LG"],
        ),
        Topic(
            name="agents",
            keywords=["agent", "tool use", "reasoning"],
            categories=["cs.AI", "cs.MA"],
        ),
    ]
    return Pipeline(
        sources=[_StaticSource(_build_fixture_papers())],
        filters=[
            RecencyFilter(max_days=7),
            RelevanceFilter(topics=topics),
            DedupFilter(loaders=[MarkdownVaultKeyLoader(root=vault)]),
        ],
        scorer=CompositeScorer(topics=topics),
        reporters=[MarkdownReporter(output_dir=output_dir)],
    )


# ---------------------------------------------------------------------------
# The regression contract
# ---------------------------------------------------------------------------


async def test_d_s_synthetic_baseline_locks_in_v0_4_0_quality(tmp_path: Path) -> None:
    """Synthetic D-S regression — locks in source/filter/scorer counts + top-K.

    If this test fails after a refactor, ask:

    * Did source coverage drop? → likely a regression in the source
      protocol or fan-in path.
    * Did filter pass-rate change? → check filter ordering, scorer
      changes that affect filter behaviour, recency-window math.
    * Did top-K ids reorder? → check CompositeScorer weights, the
      score axes, or the sort key in Pipeline.run.

    Update the snapshot only if the user explicitly accepts the new
    quality numbers.
    """
    vault = tmp_path / "vault"
    vault.mkdir()  # empty — dedup ledger excluded per D-S
    output_dir = tmp_path / "digests"

    pipeline = _make_pipeline(vault, output_dir)
    ctx = RunContext(target_date=_TARGET, config_snapshot={"recipe": "d-s-baseline"})
    result = await pipeline.run(ctx, top_k=10)

    # ------------------------------------------------------------------
    # 1. Source coverage — every paper made it past the source stage.
    # ------------------------------------------------------------------
    assert ctx.counters["source.arxiv.fetched"] == _EXPECTED_SOURCE_FETCHED, (
        f"source coverage regressed: expected {_EXPECTED_SOURCE_FETCHED}, "
        f"got {ctx.counters['source.arxiv.fetched']}"
    )

    # ------------------------------------------------------------------
    # 2. Filter pass-rate — each filter drops the documented count.
    # ------------------------------------------------------------------
    assert ctx.counters["filter.recency.dropped"] == _EXPECTED_RECENCY_DROPPED, (
        f"recency filter regressed: expected {_EXPECTED_RECENCY_DROPPED}, "
        f"got {ctx.counters['filter.recency.dropped']}"
    )
    assert ctx.counters["filter.relevance.dropped"] == _EXPECTED_RELEVANCE_DROPPED, (
        f"relevance filter regressed: expected {_EXPECTED_RELEVANCE_DROPPED}, "
        f"got {ctx.counters['filter.relevance.dropped']}"
    )
    assert ctx.counters.get("filter.dedup.dropped", 0) == _EXPECTED_DEDUP_DROPPED, (
        "D-S excludes dedup drops; the empty-vault fixture must not drop any"
    )

    # ------------------------------------------------------------------
    # 3. Scorer pass — every survivor was scored.
    # ------------------------------------------------------------------
    assert ctx.counters["scorer.composite.scored"] == _EXPECTED_SCORER_SCORED, (
        f"scorer regressed: expected {_EXPECTED_SCORER_SCORED} scored, "
        f"got {ctx.counters['scorer.composite.scored']}"
    )

    # ------------------------------------------------------------------
    # 4. Top-K ranking — exact id order locked in.
    # ------------------------------------------------------------------
    actual_top_10 = [r.paper.canonical_id for r in result.recommendations]
    assert actual_top_10 == _EXPECTED_TOP_10_IDS, (
        "top-10 ranking regressed:\n"
        f"  expected: {_EXPECTED_TOP_10_IDS}\n"
        f"  actual:   {actual_top_10}"
    )

    # ------------------------------------------------------------------
    # 5. Score sanity — composite scores stay in [0, 1] and monotonically
    #    decreasing.
    # ------------------------------------------------------------------
    scores = [r.score.composite for r in result.recommendations]
    assert all(0.0 <= s <= 1.0 for s in scores), f"composite score out of [0, 1] range: {scores}"
    assert scores == sorted(scores, reverse=True), (
        f"top-K not sorted by score (descending): {scores}"
    )
