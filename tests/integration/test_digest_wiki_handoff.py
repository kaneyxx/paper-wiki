"""Integration: digest reporter ➜ wiki backend ➜ wiki_lint handoff.

Validates the Phase 6.3 contract end-to-end:

1. ``ObsidianReporter`` runs with ``wiki_backend=True``. Each
   recommendation is persisted as a source file under
   ``Wiki/papers/`` *and* the daily digest is written under
   ``Daily/`` as usual.
2. With no concept articles yet, ``wiki_lint`` flags every freshly
   written source as ``DANGLING_SOURCE`` (severity ``info``) — the
   count must equal the number of recommendations.
3. After ``upsert_concept`` references the sources, the
   ``DANGLING_SOURCE`` findings disappear, proving the lint signal
   is the right primitive for "next: run /paperwiki:wiki-ingest".

The test never touches Claude or the network; it builds a small
recommendations list directly so the handoff contract is the only
thing under test.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from paperwiki.core.models import (
    Author,
    Paper,
    Recommendation,
    RunContext,
    ScoreBreakdown,
)
from paperwiki.plugins.backends.markdown_wiki import MarkdownWikiBackend
from paperwiki.plugins.reporters.obsidian import ObsidianReporter
from paperwiki.runners import wiki_lint as wiki_lint_runner

_NOW = datetime(2026, 4, 25, tzinfo=UTC)


def _make_rec(canonical_id: str, title: str) -> Recommendation:
    return Recommendation(
        paper=Paper(
            canonical_id=canonical_id,
            title=title,
            authors=[Author(name="Jane Doe")],
            abstract="A foundation model for X.",
            published_at=datetime(2026, 4, 20, tzinfo=UTC),
            categories=["cs.CV"],
            landing_url=f"https://arxiv.org/abs/{canonical_id.split(':', 1)[1]}",
        ),
        score=ScoreBreakdown(composite=0.75),
        matched_topics=["vision-language"],
    )


def _make_ctx() -> RunContext:
    return RunContext(target_date=_NOW, config_snapshot={})


async def test_wiki_backend_handoff_drops_top_k_into_sources(tmp_path: Path) -> None:
    """Top-K recommendations land as ``Wiki/papers/`` files."""
    top_k = 3
    recs = [_make_rec(f"arxiv:0001.{i:04d}", f"Paper {i}") for i in range(1, top_k + 1)]
    reporter = ObsidianReporter(vault_path=tmp_path, wiki_backend=True)

    ctx = _make_ctx()
    await reporter.emit(recs, ctx)

    # Daily digest written as usual.
    assert (tmp_path / "Daily" / "2026-04-25-paper-digest.md").exists()
    # Per-paper sources written via the wiki backend.
    sources_dir = tmp_path / "Wiki" / "papers"
    files = sorted(p.name for p in sources_dir.glob("*.md"))
    assert files == [
        "arxiv_0001.0001.md",
        "arxiv_0001.0002.md",
        "arxiv_0001.0003.md",
    ]
    assert ctx.counters["reporter.obsidian.wiki_backend.written"] == top_k


async def test_lint_reports_one_dangling_source_per_top_k_paper(
    tmp_path: Path,
) -> None:
    """``wiki_lint`` count of DANGLING_SOURCE matches the digest's top-K size."""
    top_k = 4
    recs = [_make_rec(f"arxiv:0001.{i:04d}", f"Paper {i}") for i in range(1, top_k + 1)]
    reporter = ObsidianReporter(vault_path=tmp_path, wiki_backend=True)
    await reporter.emit(recs, _make_ctx())

    report = await wiki_lint_runner.lint_wiki(tmp_path, now=_NOW)
    dangling = [f for f in report.findings if f.code == "DANGLING_SOURCE"]
    assert len(dangling) == top_k
    # Severity is ``info`` — opt-in chore, not a hard error.
    assert all(f.severity == "info" for f in dangling)


async def test_lint_clears_dangling_after_concept_references_source(
    tmp_path: Path,
) -> None:
    """Once a concept references the source, the lint finding goes away."""
    rec = _make_rec("arxiv:0001.0001", "Paper 1")
    reporter = ObsidianReporter(vault_path=tmp_path, wiki_backend=True)
    await reporter.emit([rec], _make_ctx())

    # Pre: source is dangling.
    pre = await wiki_lint_runner.lint_wiki(tmp_path, now=_NOW)
    assert any(f.code == "DANGLING_SOURCE" for f in pre.findings)

    # Author a concept that references the source (what wiki-ingest
    # would do after analyzing it).
    backend = MarkdownWikiBackend(vault_path=tmp_path)
    await backend.upsert_concept(
        name="Vision-Language",
        body="Synthesis drawing on [[arxiv_0001.0001]].",
        sources=["arxiv:0001.0001"],
        confidence=0.7,
        status="reviewed",
    )

    # Post: dangling finding cleared.
    post = await wiki_lint_runner.lint_wiki(tmp_path, now=_NOW)
    assert not any(f.code == "DANGLING_SOURCE" for f in post.findings)
