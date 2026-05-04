"""Task 9.211 — runner error handlers must surface the actual error message.

When any ``PaperWikiError`` is raised from a runner's inner function,
the user-facing CLI must emit the exception's message text on stderr.
loguru's default sink renders ``logger.error(event, error=str(exc))``
as the bare event name with the ``error=...`` field as a hidden
``extra``, so without an explicit :func:`typer.echo` the actionable
hint never reaches the user's terminal.

This was caught in v0.4.6 real-machine smoke (2026-05-04) when the
maintainer saw `wiki_graph_query.failed` and had no idea why —
the actual `PaperWikiError("wiki root missing: ...")` was swallowed.

The fix mirrors the existing :mod:`paperwiki.runners.digest` pattern
(line 307): :func:`typer.echo` ``str(exc)`` to stderr **before**
the structured ``logger.error`` line (which is preserved for
log-aggregation tools). Already-correct runners are tested too as
regression pins.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from typer.testing import CliRunner

from paperwiki.core.errors import PaperWikiError

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

SENTINEL = "9211 sentinel boom — must reach stderr"


def _runner() -> CliRunner:
    # Click 8.2+ separates stderr by default; older versions need
    # ``mix_stderr=False`` (passed via kwargs guard for forward-compat).
    try:
        return CliRunner(mix_stderr=False)  # type: ignore[call-arg]
    except TypeError:
        return CliRunner()


# ---------------------------------------------------------------------------
# wiki_graph_query (line 302) — was missing typer.echo
# ---------------------------------------------------------------------------


def test_wiki_graph_query_surfaces_error_to_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from paperwiki.runners import wiki_graph_query as runner

    def boom(*_args: object, **_kwargs: object) -> object:
        raise PaperWikiError(SENTINEL)

    monkeypatch.setattr(runner, "query", boom)

    result = _runner().invoke(
        runner.app,
        ["--concepts-in-topic", "foo", str(tmp_path)],
    )

    assert result.exit_code != 0
    assert SENTINEL in result.stderr, (
        f"expected {SENTINEL!r} in stderr; got stdout={result.stdout!r} stderr={result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# wiki_compile (3 catch sites: restore, restore_properties, compile_wiki)
# ---------------------------------------------------------------------------


def test_wiki_compile_compile_failed_surfaces_error_to_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Catch site at line 394 — main compile_wiki path."""
    from paperwiki.runners import wiki_compile as runner

    async def boom(*_args: object, **_kwargs: object) -> object:
        raise PaperWikiError(SENTINEL)

    monkeypatch.setattr(runner, "compile_wiki", boom)

    result = _runner().invoke(runner.app, [str(tmp_path)])

    assert result.exit_code != 0
    assert SENTINEL in result.stderr


def test_wiki_compile_restore_failed_surfaces_error_to_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Catch site at line 336 — --restore-migration path."""
    from paperwiki.runners import migrate_v04, wiki_compile

    def boom(*_args: object, **_kwargs: object) -> None:
        raise PaperWikiError(SENTINEL)

    monkeypatch.setattr(migrate_v04, "restore", boom)

    result = _runner().invoke(
        wiki_compile.app, [str(tmp_path), "--restore-migration", "20260101T000000Z"]
    )

    assert result.exit_code != 0
    assert SENTINEL in result.stderr


def test_wiki_compile_restore_properties_failed_surfaces_error_to_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Catch site at line 363 — --restore-properties path."""
    from paperwiki.runners import migrate_properties, wiki_compile

    def boom(*_args: object, **_kwargs: object) -> None:
        raise PaperWikiError(SENTINEL)

    monkeypatch.setattr(migrate_properties, "restore", boom)

    result = _runner().invoke(
        wiki_compile.app, [str(tmp_path), "--restore-properties", "20260101T000000Z"]
    )

    assert result.exit_code != 0
    assert SENTINEL in result.stderr


# ---------------------------------------------------------------------------
# wiki_lint (line 404) — was missing typer.echo
# ---------------------------------------------------------------------------


def test_wiki_lint_surfaces_error_to_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from paperwiki.runners import wiki_lint as runner

    async def boom(*_args: object, **_kwargs: object) -> object:
        raise PaperWikiError(SENTINEL)

    monkeypatch.setattr(runner, "lint_wiki", boom)

    result = _runner().invoke(runner.app, [str(tmp_path)])

    assert result.exit_code != 0
    assert SENTINEL in result.stderr


# ---------------------------------------------------------------------------
# extract_paper_images (line 389) — was missing typer.echo
# ---------------------------------------------------------------------------


def test_extract_paper_images_surfaces_error_to_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from paperwiki.runners import extract_paper_images as runner

    async def boom(*_args: object, **_kwargs: object) -> object:
        raise PaperWikiError(SENTINEL)

    monkeypatch.setattr(runner, "extract_paper_images", boom)

    result = _runner().invoke(runner.app, [str(tmp_path), "arxiv:2501.99999"])

    assert result.exit_code != 0
    assert SENTINEL in result.stderr


# ---------------------------------------------------------------------------
# migrate_recipe (line 529) — was missing typer.echo
# Note: the catch is for (ValueError, OSError), not PaperWikiError.
# ---------------------------------------------------------------------------


def test_migrate_recipe_surfaces_error_to_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from paperwiki.runners import migrate_recipe as runner

    def boom(*_args: object, **_kwargs: object) -> object:
        raise ValueError(SENTINEL)

    recipe = tmp_path / "stale.yaml"
    recipe.write_text("name: test\n", encoding="utf-8")

    monkeypatch.setattr(runner, "migrate_recipe_file", boom)

    result = _runner().invoke(runner.app, [str(recipe)])

    assert result.exit_code != 0
    assert SENTINEL in result.stderr


# ---------------------------------------------------------------------------
# migrate_sources (line 464) — was missing typer.echo
# ---------------------------------------------------------------------------


def test_migrate_sources_surfaces_error_to_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from paperwiki.runners import migrate_sources as runner

    async def boom(*_args: object, **_kwargs: object) -> object:
        raise PaperWikiError(SENTINEL)

    monkeypatch.setattr(runner, "migrate_vault", boom)

    result = _runner().invoke(runner.app, [str(tmp_path)])

    assert result.exit_code != 0
    assert SENTINEL in result.stderr


# ---------------------------------------------------------------------------
# Regression pins for runners that were ALREADY correct
# (so future refactors can't quietly remove the typer.echo line)
# ---------------------------------------------------------------------------


def test_digest_surfaces_error_to_stderr(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Already correct in v0.4.2 Phase A — pin the contract."""
    from paperwiki.runners import digest as runner

    async def boom(*_args: object, **_kwargs: object) -> int:
        raise PaperWikiError(SENTINEL)

    monkeypatch.setattr(runner, "run_digest", boom)

    recipe = tmp_path / "recipe.yaml"
    recipe.write_text("name: test\n", encoding="utf-8")

    result = _runner().invoke(runner.app, [str(recipe)])

    assert result.exit_code != 0
    assert SENTINEL in result.stderr


def test_recipe_validate_surfaces_error_to_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Already correct — pin the contract."""
    from paperwiki.core.errors import UserError
    from paperwiki.runners import recipe_validate as runner

    def boom(*_args: object, **_kwargs: object) -> object:
        raise UserError(SENTINEL)

    monkeypatch.setattr(runner, "load_recipe", boom)

    recipe = tmp_path / "recipe.yaml"
    recipe.write_text("name: test\n", encoding="utf-8")

    result = _runner().invoke(runner.app, [str(recipe)])

    assert result.exit_code != 0
    assert SENTINEL in result.stderr


def test_wiki_query_surfaces_error_to_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Already correct — pin the contract."""
    from paperwiki.runners import wiki_query as runner

    async def boom(*_args: object, **_kwargs: object) -> object:
        raise PaperWikiError(SENTINEL)

    monkeypatch.setattr(runner, "query_wiki", boom)

    result = _runner().invoke(runner.app, [str(tmp_path), "what is X"])

    assert result.exit_code != 0
    assert SENTINEL in result.stderr


def test_wiki_ingest_plan_surfaces_error_to_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Already correct — pin the contract."""
    from paperwiki.runners import wiki_ingest_plan as runner

    async def boom(*_args: object, **_kwargs: object) -> object:
        raise PaperWikiError(SENTINEL)

    monkeypatch.setattr(runner, "plan_ingest", boom)

    result = _runner().invoke(runner.app, [str(tmp_path), "arxiv:2501.99999"])

    assert result.exit_code != 0
    assert SENTINEL in result.stderr
