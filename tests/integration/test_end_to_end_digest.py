"""End-to-end integration: full pipeline produces a digest file.

Validates Phase 4's deliverable. Wires up:

* a static source (no network),
* RecencyFilter + RelevanceFilter + DedupFilter,
* CompositeScorer,
* MarkdownReporter and ObsidianReporter,

and verifies the resulting digest files contain the expected paper,
score, and matched-topic content.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from paperwiki.core.models import Author, Paper, RunContext
from paperwiki.core.pipeline import Pipeline
from paperwiki.plugins.filters import (
    DedupFilter,
    MarkdownVaultKeyLoader,
    RecencyFilter,
    RelevanceFilter,
    Topic,
)
from paperwiki.plugins.reporters import MarkdownReporter, ObsidianReporter
from paperwiki.plugins.scorers import CompositeScorer


def _make_paper(
    canonical_id: str,
    *,
    title: str,
    abstract: str,
    days_old: int,
    categories: list[str] | None = None,
    citation_count: int | None = None,
) -> Paper:
    target = datetime(2026, 4, 25, tzinfo=UTC)
    return Paper(
        canonical_id=canonical_id,
        title=title,
        authors=[Author(name="Jane Doe"), Author(name="John Roe")],
        abstract=abstract,
        published_at=target - timedelta(days=days_old),
        categories=categories or [],
        landing_url=f"https://arxiv.org/abs/{canonical_id.split(':')[1]}",
        citation_count=citation_count,
    )


def _make_ctx() -> RunContext:
    return RunContext(target_date=datetime(2026, 4, 25, tzinfo=UTC), config_snapshot={})


class StaticSource:
    name = "static"

    def __init__(self, papers: list[Paper]) -> None:
        self._papers = papers

    async def fetch(self, ctx: RunContext) -> AsyncIterator[Paper]:
        for paper in self._papers:
            yield paper


async def test_end_to_end_pipeline_writes_digest_file(tmp_path: Path) -> None:
    """One pipeline run, two reporters, two files on disk."""
    # Vault has a paper that should be dedup'd out.
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "existing.md").write_text(
        '---\npaper_id: "arxiv:1111.1111"\ntitle: "Already Noted"\n---\n',
        encoding="utf-8",
    )

    # Three papers in the source: one keeper, one too old, one already in vault.
    source_papers = [
        _make_paper(
            canonical_id="arxiv:0001.0001",
            title="A Foundation Model for Vision Language Tasks",
            abstract=(
                "We propose a novel foundation model for vision-language reasoning."
                " We conduct experiments on multiple benchmarks and report"
                " state-of-the-art results."
            ),
            days_old=2,
            categories=["cs.CV", "cs.LG"],
            citation_count=80,
        ),
        _make_paper(
            canonical_id="arxiv:0002.0002",
            title="Old Foundation Model Paper",
            abstract="An older foundation model.",
            days_old=400,
            categories=["cs.LG"],
        ),
        _make_paper(
            canonical_id="arxiv:1111.1111",
            title="Already Noted Foundation Model",
            abstract="Foundation model in vault already.",
            days_old=2,
            categories=["cs.LG"],
        ),
    ]

    topics = [Topic(name="vlm", keywords=["foundation model", "vision-language"])]
    digest_dir = tmp_path / "digests"
    obsidian_vault = tmp_path / "obsidian"

    pipeline = Pipeline(
        sources=[StaticSource(source_papers)],
        filters=[
            RecencyFilter(max_days=7),
            RelevanceFilter(topics=topics),
            DedupFilter(loaders=[MarkdownVaultKeyLoader(root=vault)]),
        ],
        scorer=CompositeScorer(topics=topics),
        reporters=[
            MarkdownReporter(output_dir=digest_dir),
            ObsidianReporter(vault_path=obsidian_vault, daily_subdir="10_Daily"),
        ],
    )

    ctx = _make_ctx()
    result = await pipeline.run(ctx, top_k=10)

    # ------------------------------------------------------------------
    # Pipeline output
    # ------------------------------------------------------------------
    assert {r.paper.canonical_id for r in result.recommendations} == {"arxiv:0001.0001"}
    assert ctx.counters["filter.recency.dropped"] == 1
    assert ctx.counters["filter.dedup.dropped"] == 1
    assert ctx.counters["scorer.composite.scored"] == 1

    # ------------------------------------------------------------------
    # MarkdownReporter file
    # ------------------------------------------------------------------
    md_path = digest_dir / "2026-04-25-paper-digest.md"
    assert md_path.exists()
    md_text = md_path.read_text(encoding="utf-8")
    assert "# Paper Digest — 2026-04-25" in md_text
    assert "## 1. A Foundation Model for Vision Language Tasks" in md_text
    assert "arxiv:0001.0001" in md_text
    assert "vlm" in md_text  # matched topic in body
    assert "Citations" in md_text

    # ------------------------------------------------------------------
    # ObsidianReporter file
    # ------------------------------------------------------------------
    ob_path = obsidian_vault / "10_Daily" / "2026-04-25-paper-digest.md"
    assert ob_path.exists()
    ob_text = ob_path.read_text(encoding="utf-8")
    assert "## 1. [[A Foundation Model for Vision Language Tasks|" in ob_text
    assert "[[vlm]]" in ob_text
    # Obsidian-flavored output adds the obsidian tag.
    assert "obsidian" in ob_text

    # ------------------------------------------------------------------
    # Score sanity
    # ------------------------------------------------------------------
    rec = result.recommendations[0]
    assert 0.0 <= rec.score.composite <= 1.0
    assert rec.score.relevance > 0.0
    assert "vlm" in rec.matched_topics


async def test_pipeline_with_no_recommendations_still_writes_digest(tmp_path: Path) -> None:
    """A digest file is written even when zero papers survive filtering."""
    pipeline = Pipeline(
        sources=[StaticSource([])],
        filters=[],
        scorer=CompositeScorer(topics=[Topic(name="x", keywords=["x"])]),
        reporters=[
            MarkdownReporter(output_dir=tmp_path / "out"),
        ],
    )

    ctx = _make_ctx()
    result = await pipeline.run(ctx)

    assert result.recommendations == []
    md_path = tmp_path / "out" / "2026-04-25-paper-digest.md"
    assert md_path.exists()
    text = md_path.read_text(encoding="utf-8")
    assert "_No recommendations matched the pipeline today._" in text
    assert "recommendations: 0" in text
