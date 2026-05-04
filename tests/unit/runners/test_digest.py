"""Unit tests for paperwiki.runners.digest."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from paperwiki.core.errors import IntegrationError, UserError
from paperwiki.core.models import (
    Author,
    Paper,
    Recommendation,
    RunContext,
    ScoreBreakdown,
)
from paperwiki.core.pipeline import Pipeline
from paperwiki.runners import digest as digest_runner

_RECIPE_YAML = """\
name: smoke
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


def _write_recipe(tmp_path: Path) -> Path:
    output_dir = tmp_path / "out"
    recipe_path = tmp_path / "r.yaml"
    recipe_path.write_text(
        _RECIPE_YAML.format(output_dir=output_dir),
        encoding="utf-8",
    )
    return recipe_path


# ---------------------------------------------------------------------------
# Stub plugins for runner tests
# ---------------------------------------------------------------------------


class _StubSource:
    name = "stub"

    async def fetch(self, ctx: RunContext) -> AsyncIterator[Paper]:
        yield Paper(
            canonical_id="arxiv:0001.0001",
            title="Foundation Model",
            authors=[Author(name="A")],
            abstract="abstract",
            published_at=datetime(2026, 4, 20, tzinfo=UTC),
        )


class _StubScorer:
    name = "stub-scorer"

    async def score(
        self,
        papers: AsyncIterator[Paper],
        ctx: RunContext,
    ) -> AsyncIterator[Recommendation]:
        async for paper in papers:
            yield Recommendation(paper=paper, score=ScoreBreakdown(composite=0.5))


class _StubReporter:
    name = "stub-reporter"

    def __init__(self) -> None:
        self.received: list[Recommendation] | None = None

    async def emit(self, recs: list[Recommendation], ctx: RunContext) -> None:
        self.received = list(recs)


def _stub_pipeline() -> tuple[Pipeline, _StubReporter]:
    reporter = _StubReporter()
    pipeline = Pipeline(
        sources=[_StubSource()],
        filters=[],
        scorer=_StubScorer(),
        reporters=[reporter],
    )
    return pipeline, reporter


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------


class TestParseDate:
    def test_parses_iso_date(self) -> None:
        result = digest_runner._parse_date("2026-04-25")
        assert result == datetime(2026, 4, 25, tzinfo=UTC)

    def test_invalid_format_raises(self) -> None:
        import typer

        with pytest.raises(typer.BadParameter, match="YYYY-MM-DD"):
            digest_runner._parse_date("4/25/2026")


# ---------------------------------------------------------------------------
# run_digest (async core)
# ---------------------------------------------------------------------------


class TestRunDigest:
    async def test_returns_zero_on_success(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        pipeline, reporter = _stub_pipeline()
        monkeypatch.setattr(digest_runner, "instantiate_pipeline", lambda recipe: pipeline)

        recipe_path = _write_recipe(tmp_path)
        exit_code = await digest_runner.run_digest(recipe_path)

        assert exit_code == 0
        assert reporter.received is not None
        assert len(reporter.received) == 1

    async def test_target_date_overrides_today(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        pipeline, _reporter = _stub_pipeline()
        captured: dict[str, datetime] = {}

        original_run = pipeline.run

        async def capture_run(ctx: RunContext, *args: object, **kwargs: object) -> object:
            captured["target"] = ctx.target_date
            return await original_run(ctx, *args, **kwargs)  # type: ignore[arg-type]

        pipeline.run = capture_run  # type: ignore[method-assign]

        monkeypatch.setattr(digest_runner, "instantiate_pipeline", lambda recipe: pipeline)

        target = datetime(2026, 4, 25, tzinfo=UTC)
        recipe_path = _write_recipe(tmp_path)
        await digest_runner.run_digest(recipe_path, target_date=target)

        assert captured["target"] == target

    async def test_uses_recipe_top_k(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        pipeline, _ = _stub_pipeline()
        captured: dict[str, object] = {}

        async def capture_run(ctx: RunContext, *args: object, **kwargs: object) -> object:
            captured["top_k"] = kwargs.get("top_k") or (args[0] if args else None)
            return MagicMock(recommendations=[], counters={})

        pipeline.run = capture_run  # type: ignore[method-assign]
        monkeypatch.setattr(digest_runner, "instantiate_pipeline", lambda recipe: pipeline)

        recipe_path = _write_recipe(tmp_path)
        await digest_runner.run_digest(recipe_path)

        assert captured["top_k"] == 5  # from recipe yaml above

    async def test_missing_recipe_raises_user_error(self, tmp_path: Path) -> None:
        with pytest.raises(UserError):
            await digest_runner.run_digest(tmp_path / "missing.yaml")


# ---------------------------------------------------------------------------
# Typer CLI
# ---------------------------------------------------------------------------


class TestCliEntryPoint:
    def test_success_exits_zero(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        pipeline, _ = _stub_pipeline()
        monkeypatch.setattr(digest_runner, "instantiate_pipeline", lambda recipe: pipeline)

        recipe_path = _write_recipe(tmp_path)
        runner = CliRunner()
        result = runner.invoke(digest_runner.app, [str(recipe_path)])

        assert result.exit_code == 0

    def test_user_error_exits_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def boom(*args: object, **kwargs: object) -> int:
            raise UserError("bad config")

        monkeypatch.setattr(digest_runner, "run_digest", boom)

        recipe_path = _write_recipe(tmp_path)
        runner = CliRunner()
        result = runner.invoke(digest_runner.app, [str(recipe_path)])

        assert result.exit_code == 1

    def test_integration_error_exits_two(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def boom(*args: object, **kwargs: object) -> int:
            raise IntegrationError("network down")

        monkeypatch.setattr(digest_runner, "run_digest", boom)

        recipe_path = _write_recipe(tmp_path)
        runner = CliRunner()
        result = runner.invoke(digest_runner.app, [str(recipe_path)])

        assert result.exit_code == 2

    def test_invalid_target_date_rejected_by_typer(
        self,
        tmp_path: Path,
    ) -> None:
        recipe_path = _write_recipe(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            digest_runner.app,
            [str(recipe_path), "--target-date", "not-a-date"],
        )

        assert result.exit_code != 0
        assert "YYYY-MM-DD" in result.output

    def test_auto_loads_secrets_env_before_pipeline_init(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Task 9.180 / D-U integration: ``paperwiki digest <recipe>`` from a
        clean shell (no prior ``source secrets.env``) succeeds because the
        runner auto-loads ``${PAPERWIKI_HOME}/secrets.env`` before
        ``instantiate_pipeline`` reads ``os.environ``.

        Captures the env at the moment ``instantiate_pipeline`` is called and
        asserts the secrets-loaded var is present — this is the exact moment
        ``_resolve_s2_secrets`` would crash on a clean shell pre-D-U.
        """
        import os

        from paperwiki.config import secrets as secrets_mod

        # Fresh idempotency state for this test (the loader is process-wide
        # but the test suite must reset between scenarios).
        secrets_mod.reset_for_testing()

        # Sandbox PAPERWIKI_HOME under tmp_path with a secrets.env that
        # exports a fake S2 key.
        home = tmp_path / "paperwiki-home"
        home.mkdir()
        (home / "secrets.env").write_text(
            "PAPERWIKI_S2_API_KEY=auto_loaded_from_file\n",
            encoding="utf-8",
        )
        (home / "secrets.env").chmod(0o600)
        monkeypatch.setenv("PAPERWIKI_HOME", str(home))
        # Scrub any pre-existing key so the only path to the value is via
        # the secrets loader.
        monkeypatch.delenv("PAPERWIKI_S2_API_KEY", raising=False)
        monkeypatch.delenv("PAPERWIKI_NO_AUTO_SECRETS", raising=False)

        captured: dict[str, str | None] = {}

        def _capture_env_at_pipeline_init(recipe: object) -> Pipeline:
            captured["s2_key"] = os.environ.get("PAPERWIKI_S2_API_KEY")
            pipeline, _ = _stub_pipeline()
            return pipeline

        monkeypatch.setattr(
            digest_runner,
            "instantiate_pipeline",
            _capture_env_at_pipeline_init,
        )

        try:
            recipe_path = _write_recipe(tmp_path)
            runner = CliRunner()
            result = runner.invoke(digest_runner.app, [str(recipe_path)])
        finally:
            secrets_mod.reset_for_testing()

        assert result.exit_code == 0, result.output
        assert captured["s2_key"] == "auto_loaded_from_file", (
            "load_secrets_env() must run before instantiate_pipeline so the "
            "S2 source's api_key_env indirection resolves"
        )
