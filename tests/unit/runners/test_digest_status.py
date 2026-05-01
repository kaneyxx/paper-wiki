"""Digest runner ↔ run-status ledger wiring (task 9.167 / decision **D-O**).

Every digest run appends one JSONL line to
``<vault>/.paperwiki/run-status.jsonl`` summarising what happened —
papers fetched per source, filter drops, final recommendation count,
elapsed time, plus an error class/message when the run failed.

Three flavours of test live here:

* **Happy-path append** — a clean digest writes a ``final_count`` and
  zero error fields; per-source / per-filter counters round-trip.
* **Failure-mode append** — a ``UserError`` (no papers) and an
  ``IntegrationError`` (source raised) both produce a ledger entry
  with ``error_class`` populated.
* **Vault resolution** — the runner finds the vault via the obsidian
  reporter's ``vault_path``; recipes without an obsidian reporter are
  silently no-op (the ledger is vault-bound by **D-O**).

The runner-level tests use the real pipeline + a stub source/scorer
to keep the feedback loop fast (no network, no fixture digest files).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from paperwiki._internal.run_status import LEDGER_DIR, LEDGER_FILE
from paperwiki.core.errors import IntegrationError
from paperwiki.core.models import (
    Author,
    Paper,
    Recommendation,
    RunContext,
    ScoreBreakdown,
)
from paperwiki.core.pipeline import Pipeline
from paperwiki.runners import digest as digest_runner

_RECIPE_TEMPLATE_OBSIDIAN = """\
name: smoke-status
sources:
  - name: arxiv
    config:
      categories: [cs.AI]
      lookback_days: 1
filters: []
scorer:
  name: composite
  config:
    topics:
      - name: vlm
        keywords: [foundation model]
reporters:
  - name: markdown
    config:
      output_dir: {output_dir}
  - name: obsidian
    config:
      vault_path: {vault}
      daily_subdir: Daily
top_k: 5
"""

_RECIPE_TEMPLATE_NO_OBSIDIAN = """\
name: smoke-no-vault
sources:
  - name: arxiv
    config:
      categories: [cs.AI]
      lookback_days: 1
filters: []
scorer:
  name: composite
  config:
    topics:
      - name: vlm
        keywords: [foundation model]
reporters:
  - name: markdown
    config:
      output_dir: {output_dir}
top_k: 5
"""


def _write_recipe(tmp_path: Path, *, with_obsidian: bool = True) -> tuple[Path, Path]:
    output_dir = tmp_path / "out"
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    recipe_path = tmp_path / "r.yaml"
    template = _RECIPE_TEMPLATE_OBSIDIAN if with_obsidian else _RECIPE_TEMPLATE_NO_OBSIDIAN
    recipe_path.write_text(
        template.format(output_dir=output_dir, vault=vault),
        encoding="utf-8",
    )
    return recipe_path, vault


# ---------------------------------------------------------------------------
# Stub plugins (reused from test_digest patterns)
# ---------------------------------------------------------------------------


class _OneShotSource:
    name = "arxiv"

    async def fetch(self, ctx: RunContext) -> AsyncIterator[Paper]:
        yield Paper(
            canonical_id="arxiv:0001.0001",
            title="Foundation Model",
            authors=[Author(name="A")],
            abstract="abstract",
            published_at=datetime(2026, 4, 20, tzinfo=UTC),
        )


class _RaisingSource:
    name = "arxiv"

    async def fetch(self, ctx: RunContext) -> AsyncIterator[Paper]:
        msg = "S2 returned HTTP 429"
        raise IntegrationError(msg)
        yield  # pragma: no cover - unreachable, here for typing


class _DropAllFilter:
    name = "drop-all"

    async def apply(self, papers: AsyncIterator[Paper], ctx: RunContext) -> AsyncIterator[Paper]:
        async for _paper in papers:
            ctx.increment(f"filter.{self.name}.dropped")
        return
        yield  # pragma: no cover - unreachable


class _StubScorer:
    name = "stub-scorer"

    async def score(
        self, papers: AsyncIterator[Paper], ctx: RunContext
    ) -> AsyncIterator[Recommendation]:
        async for paper in papers:
            yield Recommendation(paper=paper, score=ScoreBreakdown(composite=0.5))


class _NoopReporter:
    name = "noop"

    async def emit(self, recs: list[Recommendation], ctx: RunContext) -> None:
        return None


def _make_pipeline(
    *,
    raise_source: bool = False,
    drop_all: bool = False,
) -> Pipeline:
    source = _RaisingSource() if raise_source else _OneShotSource()
    return Pipeline(
        sources=[source],
        filters=[_DropAllFilter()] if drop_all else [],
        scorer=_StubScorer(),
        reporters=[_NoopReporter()],
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestRunStatusLedgerHappyPath:
    async def test_appends_one_line_to_vault_ledger(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recipe_path, vault = _write_recipe(tmp_path, with_obsidian=True)
        monkeypatch.setattr(digest_runner, "instantiate_pipeline", lambda recipe: _make_pipeline())
        await digest_runner.run_digest(recipe_path)

        ledger = vault / LEDGER_DIR / LEDGER_FILE
        assert ledger.is_file()
        text = ledger.read_text(encoding="utf-8").strip()
        rows = [json.loads(line) for line in text.splitlines() if line]
        assert len(rows) == 1
        row = rows[0]
        assert row["recipe"] == "smoke-status"
        assert row["final_count"] == 1
        assert row["error_class"] is None
        # Source counters round-trip from RunContext.
        assert row["source_counts"] == {"arxiv": 1}
        assert row["source_errors"] == {}

    async def test_records_filter_drops(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recipe_path, vault = _write_recipe(tmp_path, with_obsidian=True)
        monkeypatch.setattr(
            digest_runner,
            "instantiate_pipeline",
            lambda recipe: _make_pipeline(drop_all=True),
        )
        await digest_runner.run_digest(recipe_path)

        ledger = vault / LEDGER_DIR / LEDGER_FILE
        text = ledger.read_text(encoding="utf-8").strip()
        row = json.loads(text.splitlines()[-1])
        assert row["filter_drops"] == {"drop-all": 1}
        assert row["final_count"] == 0


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


class TestRunStatusLedgerFailureModes:
    async def test_source_raised_records_source_errors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recipe_path, vault = _write_recipe(tmp_path, with_obsidian=True)
        monkeypatch.setattr(
            digest_runner,
            "instantiate_pipeline",
            lambda recipe: _make_pipeline(raise_source=True),
        )
        # Pipeline isolates IntegrationError per-source — the run completes
        # with zero recommendations rather than raising.
        await digest_runner.run_digest(recipe_path)

        ledger = vault / LEDGER_DIR / LEDGER_FILE
        text = ledger.read_text(encoding="utf-8").strip()
        row = json.loads(text.splitlines()[-1])
        assert row["source_errors"] == {"arxiv": 1}
        assert row["final_count"] == 0
        # error_class stays None because the run completed —
        # source-level rate-limits don't promote to a run-level failure
        # (see Pipeline._drain_sources for the contract).
        assert row["error_class"] is None

    async def test_user_error_records_error_class_and_rerases(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from paperwiki.core.errors import UserError

        recipe_path, vault = _write_recipe(tmp_path, with_obsidian=True)

        def boom(_recipe: object) -> Pipeline:
            msg = "instantiate_pipeline failed"
            raise UserError(msg)

        monkeypatch.setattr(digest_runner, "instantiate_pipeline", boom)

        with pytest.raises(UserError):
            await digest_runner.run_digest(recipe_path)

        ledger = vault / LEDGER_DIR / LEDGER_FILE
        # Even on a hard failure, the runner appended a row so the user
        # can audit failed runs via ``paperwiki status``.
        assert ledger.is_file(), "expected ledger entry on UserError"
        row = json.loads(ledger.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert row["error_class"] == "UserError"
        assert row["error_message"] == "instantiate_pipeline failed"
        assert row["final_count"] == 0


# ---------------------------------------------------------------------------
# Vault resolution
# ---------------------------------------------------------------------------


class TestVaultResolution:
    async def test_no_obsidian_reporter_means_no_ledger(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Per **D-O** the ledger is vault-bound. No vault → no ledger.

        Recipes that ship pure-Markdown (no Obsidian reporter) have
        nowhere to put the ledger; the runner silently no-ops rather
        than picking an arbitrary directory.
        """
        recipe_path, vault = _write_recipe(tmp_path, with_obsidian=False)
        monkeypatch.setattr(digest_runner, "instantiate_pipeline", lambda recipe: _make_pipeline())
        await digest_runner.run_digest(recipe_path)

        ledger = vault / LEDGER_DIR / LEDGER_FILE
        assert not ledger.exists()
