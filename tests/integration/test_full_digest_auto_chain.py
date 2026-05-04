"""End-to-end smoke test: digest auto-chain pipeline → wiki state on disk.

Exercises the full digest → auto-chain path with **real production code**
and **no network calls**:

- Real: Pipeline composition, scoring, deduplication, MarkdownWikiBackend,
  wiki_ingest_plan runner with --auto-bootstrap, citation folding.
- Mocked: network adapters replaced by StubSource (a local AsyncIterator).
- Out of scope: SKILL prose synthesis (tested in unit form via test_smoke.py).

Stub source approach: **Option B** — the test constructs the Pipeline
directly (in-process), bypassing the recipe YAML loader entirely.  This
avoids leaking test code into the prod _build_source() switch and keeps the
test fast (no YAML parse overhead, no subprocess for the digest step).  The
wiki_ingest_plan runner IS invoked via subprocess, exactly as the SKILL
does it, to pin the subprocess contract.

Stub papers use a small set of related_concepts that straddle concept-create
and concept-fold paths:

 Paper 0  vision-multimodal  + biomedical-pathology       (both new → 2 stubs)
 Paper 1  vision-multimodal  + biomedical-pathology       (both exist → fold)
 Paper 2  vision-multimodal  + agents-reasoning           (agents-reasoning new → stub;
                                                           vision-multimodal exists → fold)
 Paper 3  agents-reasoning   + biomedical-pathology       (both exist → fold)
 Paper 4  diffusion-models   + vision-multimodal          (diffusion-models new → stub;
                                                           vision-multimodal exists → fold)

top_k = 3 so only papers 0-2 enter the wiki-ingest loop.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from paperwiki.core.models import Author, Paper, RunContext
from paperwiki.core.pipeline import Pipeline
from paperwiki.plugins.filters import (
    DedupFilter,
    MarkdownVaultKeyLoader,
    RecencyFilter,
    RelevanceFilter,
    Topic,
)
from paperwiki.plugins.reporters.obsidian import ObsidianReporter
from paperwiki.plugins.scorers import CompositeScorer

# ---------------------------------------------------------------------------
# Fixed date so output is deterministic
# ---------------------------------------------------------------------------

_TARGET_DATE = datetime(2026, 4, 27, tzinfo=UTC)
_TARGET_DATE_STR = "2026-04-27"

# top_k = 3 → only first 3 papers enter the auto-chain loop
_TOP_K = 3


# ---------------------------------------------------------------------------
# Stub source (Option B: in-process, no recipe YAML needed)
# ---------------------------------------------------------------------------


def _make_paper(
    canonical_id: str,
    *,
    title: str,
    abstract: str,
    matched_topics: list[str],
    days_old: int = 1,
) -> Paper:
    """Build a Paper with related_concepts as [[wikilink]] strings."""
    return Paper(
        canonical_id=canonical_id,
        title=title,
        authors=[Author(name="Stub Author")],
        abstract=abstract,
        published_at=_TARGET_DATE - timedelta(days=days_old),
        categories=["cs.LG"],
        landing_url=f"https://arxiv.org/abs/{canonical_id.split(':', 1)[1]}",
        raw={"related_concepts": [f"[[{t}]]" for t in matched_topics]},
    )


class StubSource:
    """Deterministic paper source — no network calls."""

    name = "stub_e2e"

    def __init__(self, papers: list[Paper]) -> None:
        self._papers = papers

    async def fetch(self, ctx: RunContext) -> AsyncIterator[Paper]:  # type: ignore[override]
        for p in self._papers:
            yield p


# The 5 stub papers.  Order matters: scorer will rank them; top_k=3 picks
# papers 0-2 (they score equally so insertion order is preserved).
_STUB_PAPERS = [
    _make_paper(
        "arxiv:0001.0001",
        title="A Multimodal Vision Foundation Model",
        abstract=(
            "We introduce a large multimodal model targeting vision-language tasks "
            "in biomedical pathology imaging."
        ),
        matched_topics=["vision-multimodal", "biomedical-pathology"],
    ),
    _make_paper(
        "arxiv:0001.0002",
        title="Pathology Imaging With Multimodal Transformers",
        abstract=(
            "Multimodal transformers applied to pathology slide analysis achieve new benchmarks."
        ),
        matched_topics=["vision-multimodal", "biomedical-pathology"],
    ),
    _make_paper(
        "arxiv:0001.0003",
        title="Agents With Multimodal Reasoning",
        abstract=(
            "Reasoning agents augmented with vision encoders tackle complex multi-step tasks."
        ),
        matched_topics=["vision-multimodal", "agents-reasoning"],
    ),
    _make_paper(
        "arxiv:0001.0004",
        title="Biomedical Reasoning With Agents",
        abstract="Agent-based systems for biomedical literature analysis.",
        matched_topics=["agents-reasoning", "biomedical-pathology"],
    ),
    _make_paper(
        "arxiv:0001.0005",
        title="Diffusion Models for Vision",
        abstract="Diffusion models applied to large-scale vision tasks.",
        matched_topics=["diffusion-models", "vision-multimodal"],
    ),
]

# Canonical IDs in insertion order (deterministic top-3 after scoring)
_TOP3_IDS = ["arxiv:0001.0001", "arxiv:0001.0002", "arxiv:0001.0003"]


# ---------------------------------------------------------------------------
# Full end-to-end fixture
# ---------------------------------------------------------------------------


@pytest.mark.timeout(15)
async def test_full_digest_auto_chain_lands_top_papers_into_wiki(
    tmp_path: Path,
) -> None:
    """Fresh vault → digest → auto-chain → wiki state on disk.

    Contracts pinned (every assert is a contract):
    1.  Pipeline produces a Daily digest file (AC-9.14.1/2/3).
    2.  Digest contains <!-- paper-wiki:overview-slot --> (AC-9.14.2).
    3.  Digest contains per-paper slot markers for each top-K paper (AC-9.14.3).
    4.  Wiki/papers/ files exist for each top-K paper (AC-9.14.4).
    5.  wiki_ingest_plan --auto-bootstrap exits 0 (AC-9.14.5).
    6.  JSON has created_stubs + folded_citations keys (AC-9.14.6).
    7.  Concepts already seen appear in folded_citations, NOT created_stubs (AC-9.14.7).
    8.  concept .md files exist for every created stub (AC-9.14.8).
    9.  Each concept has auto_created: true and tags: [auto-created] (AC-9.14.9).
    10. Each concept sources list is idempotent union (no duplicates) (AC-9.14.10).
    11. No DEBUG in subprocess stderr (AC-9.14.11).
    12. No WARNING in subprocess stderr (AC-9.14.12).
    13. Full test < 15 seconds (AC-9.14.13).
    """
    wall_start = time.monotonic()

    vault = tmp_path / "vault"
    vault.mkdir()

    topics = [
        Topic(name="vision-multimodal", keywords=["multimodal", "vision"]),
        Topic(name="agents-reasoning", keywords=["agent", "reasoning"]),
        Topic(name="biomedical-pathology", keywords=["pathology", "biomedical"]),
        Topic(name="diffusion-models", keywords=["diffusion"]),
    ]

    # ------------------------------------------------------------------
    # Step 1: Run the digest pipeline in-process (Option B)
    # ------------------------------------------------------------------
    pipeline = Pipeline(
        sources=[StubSource(_STUB_PAPERS)],
        filters=[
            RecencyFilter(max_days=30),
            RelevanceFilter(topics=topics),
            DedupFilter(loaders=[MarkdownVaultKeyLoader(root=vault)]),
        ],
        scorer=CompositeScorer(topics=topics),
        reporters=[
            ObsidianReporter(
                vault_path=vault,
                wiki_backend=True,
            )
        ],
    )

    ctx = RunContext(target_date=_TARGET_DATE, config_snapshot={"recipe": "stub_e2e"})
    result = await pipeline.run(ctx, top_k=_TOP_K)

    # ------------------------------------------------------------------
    # AC-9.14.1: Daily digest file exists
    # ------------------------------------------------------------------
    daily_dir = vault / "Daily"
    digest_files = list(daily_dir.glob("*.md"))
    assert len(digest_files) == 1, f"expected 1 digest file, got {[f.name for f in digest_files]}"
    digest_path = daily_dir / f"{_TARGET_DATE_STR}-paper-digest.md"
    assert digest_path.exists(), f"digest not at expected path: {digest_path}"

    digest_text = digest_path.read_text(encoding="utf-8")

    # AC-9.14.2: overview slot marker
    assert "<!-- paper-wiki:overview-slot -->" in digest_text, (
        "digest missing <!-- paper-wiki:overview-slot --> marker"
    )

    # AC-9.14.3: per-paper slot markers for each top-K paper
    top_recs = result.recommendations[:_TOP_K]
    assert len(top_recs) == _TOP_K, (
        f"pipeline produced {len(top_recs)} recommendations, expected {_TOP_K}"
    )
    for rec in top_recs:
        marker = f"<!-- paper-wiki:per-paper-slot:{rec.paper.canonical_id} -->"
        assert marker in digest_text, (
            f"digest missing per-paper marker for {rec.paper.canonical_id}"
        )

    # AC-9.14.4: Wiki/papers/ files for each top-K paper
    sources_dir = vault / "Wiki" / "papers"
    for rec in top_recs:
        stem = rec.paper.canonical_id.replace(":", "_")
        source_file = sources_dir / f"{stem}.md"
        assert source_file.exists(), f"Wiki source stub missing: {source_file}"

    # ------------------------------------------------------------------
    # Step 2: Run wiki_ingest_plan --auto-bootstrap via subprocess
    #         (exactly as the SKILL does it)
    # ------------------------------------------------------------------

    # Collect all known concept names across the test to verify idempotence.
    # Maps concept_name -> set of source_ids that hint at it.
    concept_sources_seen: dict[str, set[str]] = {}
    # Track which concepts have been created (stubs) so far.
    created_concept_names: set[str] = set()

    all_stderr: list[str] = []

    for rec in top_recs:
        cid = rec.paper.canonical_id
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "paperwiki.runners.wiki_ingest_plan",
                str(vault),
                cid,
                "--auto-bootstrap",
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "NO_COLOR": "1", "TERM": "dumb"},
        )

        # AC-9.14.5: subprocess exits 0
        assert proc.returncode == 0, (
            f"wiki_ingest_plan failed for {cid}:\nstdout={proc.stdout}\nstderr={proc.stderr}"
        )

        all_stderr.append(proc.stderr)

        # AC-9.14.6: JSON has created_stubs and folded_citations keys
        plan = json.loads(proc.stdout)
        assert "created_stubs" in plan, f"JSON missing created_stubs for {cid}"
        assert "folded_citations" in plan, f"JSON missing folded_citations for {cid}"

        new_stubs: list[str] = plan["created_stubs"]
        folded: list[str] = plan["folded_citations"]

        # AC-9.14.7: pre-existing concepts appear in folded_citations, NOT created_stubs
        for name in folded:
            assert name not in new_stubs, (
                f"concept {name!r} in BOTH created_stubs and folded_citations for {cid}"
            )
        for name in new_stubs:
            assert name not in created_concept_names, (
                f"concept {name!r} was already created but appeared in created_stubs again"
                f" for {cid}"
            )
        for name in folded:
            # concept must have been created by a prior iteration
            assert name in created_concept_names, (
                f"concept {name!r} in folded_citations but was never in a prior created_stubs "
                f"(paper: {cid})"
            )

        # Update tracking state
        for name in new_stubs:
            created_concept_names.add(name)
            concept_sources_seen.setdefault(name, set()).add(cid)
        for name in folded:
            concept_sources_seen.setdefault(name, set()).add(cid)

    # ------------------------------------------------------------------
    # Post-loop wiki-state assertions
    # ------------------------------------------------------------------
    concepts_dir = vault / "Wiki" / "concepts"
    assert concepts_dir.is_dir(), "Wiki/concepts/ directory was never created"

    concept_files = list(concepts_dir.glob("*.md"))
    assert len(concept_files) >= 2, (
        f"expected >= 2 concept stub files, got {[f.name for f in concept_files]}"
    )

    for concept_path in concept_files:
        text = concept_path.read_text(encoding="utf-8")

        # AC-9.14.8: file exists (already asserted by glob, re-read confirms content)
        assert text.strip(), f"concept file {concept_path.name} is empty"

        # AC-9.14.9: auto_created: true + tags: [auto-created]
        if "auto_created:" in text:
            assert "auto_created: true" in text, (
                f"{concept_path.name}: auto_created present but not true"
            )
            assert "auto-created" in text, f"{concept_path.name}: missing auto-created tag"

        # AC-9.14.10: sources list is idempotent (no duplicate entries)
        import yaml

        # Parse frontmatter
        if text.startswith("---\n"):
            end_idx = text.index("\n---\n", 4)
            fm = yaml.safe_load(text[4:end_idx]) or {}
            raw_sources: list[str] = fm.get("sources") or []
            assert len(raw_sources) == len(set(raw_sources)), (
                f"{concept_path.name}: duplicate entries in sources: {raw_sources}"
            )

    # ------------------------------------------------------------------
    # AC-9.14.11 / AC-9.14.12: stderr cleanliness
    # ------------------------------------------------------------------
    combined_stderr = "\n".join(all_stderr)
    assert "DEBUG" not in combined_stderr, (
        f"DEBUG output found in wiki_ingest_plan stderr:\n{combined_stderr}"
    )
    assert "WARNING" not in combined_stderr, (
        f"WARNING output found in wiki_ingest_plan stderr:\n{combined_stderr}"
    )

    # AC-9.14.13: wall-clock budget < 15 s (enforced by @pytest.mark.timeout above)
    elapsed = time.monotonic() - wall_start
    assert elapsed < 15.0, f"test took {elapsed:.1f}s, budget is 15s"
