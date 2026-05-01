"""wiki-query ranking tests (task 9.171).

Replaces the v0.3.x pure-keyword count with a frequency * recency *
tag-match composite score:

* **Frequency** — how often query terms appear in the title + body
  text. TF-style — repeats compound but with diminishing returns
  via sqrt to avoid spammy notes dominating.
* **Recency** — newer notes rank higher. Half-life decay against
  file mtime so a year-old note carries less weight than a fresh
  one when both match equally.
* **Tag-match** — boost when a query term matches a frontmatter
  tag exactly (already-existing signal, kept).

Weights are configurable via the new ``RankingWeights`` dataclass and
the CLI flags ``--weight-frequency`` / ``--weight-recency`` /
``--weight-tag-match``. Default weights live in
``references/wiki-query-ranking.md`` and are tuned against the
project's own ``.omc/wiki/`` so a representative search ("ralph
boulder") still surfaces the canonical decision page.

This module exercises the scoring contract directly. Integration
tests for the runner CLI live in tests/unit/runners/test_wiki_query.py.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

from paperwiki.runners.wiki_query import (
    RankingWeights,
    score_document,
)


def _make_doc(tmp_path: Path, body: str, *, name: str = "doc.md") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Frequency component
# ---------------------------------------------------------------------------


class TestFrequencyScoring:
    def test_more_term_occurrences_means_higher_score(self, tmp_path: Path) -> None:
        a = _make_doc(tmp_path, "vision-language model.\n\nWe use VLM here.", name="a.md")
        b = _make_doc(
            tmp_path,
            "vision-language vision-language vision-language.",
            name="b.md",
        )
        weights = RankingWeights()
        score_a = score_document(
            terms=["vision-language"],
            title="A",
            tags=[],
            body_path=a,
            weights=weights,
        )
        score_b = score_document(
            terms=["vision-language"],
            title="B",
            tags=[],
            body_path=b,
            weights=weights,
        )
        assert score_b > score_a

    def test_zero_match_returns_zero(self, tmp_path: Path) -> None:
        a = _make_doc(tmp_path, "completely unrelated text")
        weights = RankingWeights()
        score = score_document(
            terms=["vision-language"],
            title="A",
            tags=[],
            body_path=a,
            weights=weights,
        )
        assert score == 0.0


# ---------------------------------------------------------------------------
# Recency component
# ---------------------------------------------------------------------------


class TestRecencyScoring:
    def test_newer_doc_outranks_older_when_term_count_equal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Equal frequency + tag-match → recency tiebreaks."""
        old = _make_doc(tmp_path, "vision-language", name="old.md")
        new = _make_doc(tmp_path, "vision-language", name="new.md")
        # Stamp old as 365 days behind now; new as just-modified.
        very_old = (datetime.now(UTC) - timedelta(days=365)).timestamp()
        os.utime(old, (very_old, very_old))

        weights = RankingWeights()
        s_old = score_document(
            terms=["vision-language"],
            title="O",
            tags=[],
            body_path=old,
            weights=weights,
        )
        s_new = score_document(
            terms=["vision-language"],
            title="N",
            tags=[],
            body_path=new,
            weights=weights,
        )
        assert s_new > s_old


# ---------------------------------------------------------------------------
# Tag-match component
# ---------------------------------------------------------------------------


class TestTagMatch:
    def test_tag_match_boosts_score(self, tmp_path: Path) -> None:
        body = _make_doc(tmp_path, "some content")
        weights = RankingWeights()
        without_tag = score_document(
            terms=["vlm"],
            title="X",
            tags=[],
            body_path=body,
            weights=weights,
        )
        with_tag = score_document(
            terms=["vlm"],
            title="X",
            tags=["vlm"],
            body_path=body,
            weights=weights,
        )
        assert with_tag > without_tag


# ---------------------------------------------------------------------------
# Configurable weights
# ---------------------------------------------------------------------------


class TestConfigurableWeights:
    def test_zero_recency_weight_disables_recency_signal(self, tmp_path: Path) -> None:
        """Setting recency=0 should make old + new score identically."""
        old = _make_doc(tmp_path, "vision-language", name="old.md")
        new = _make_doc(tmp_path, "vision-language", name="new.md")
        very_old = (datetime.now(UTC) - timedelta(days=365)).timestamp()
        os.utime(old, (very_old, very_old))

        weights = RankingWeights(frequency=1.0, recency=0.0, tag_match=0.0)
        s_old = score_document(
            terms=["vision-language"],
            title="O",
            tags=[],
            body_path=old,
            weights=weights,
        )
        s_new = score_document(
            terms=["vision-language"],
            title="N",
            tags=[],
            body_path=new,
            weights=weights,
        )
        assert s_old == s_new

    def test_default_weights_documented(self) -> None:
        """The shipped defaults must be reachable from a single source of truth."""
        weights = RankingWeights()
        assert weights.frequency > 0
        assert weights.recency > 0
        assert weights.tag_match > 0
