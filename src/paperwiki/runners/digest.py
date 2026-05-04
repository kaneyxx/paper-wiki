"""``paperwiki.runners.digest`` — build a research digest from a recipe.

Invoked by the ``paperwiki:digest`` SKILL via::

    ${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.digest <recipe.yaml>

The runner is a thin shell:

1. Parse and validate the recipe YAML.
2. Instantiate the Pipeline.
3. Build a :class:`RunContext` (timezone-aware ``target_date``).
4. Run the pipeline.
5. Append a row to ``<vault>/.paperwiki/run-status.jsonl`` (task 9.167)
   capturing source counts, filter drops, final paper count, elapsed
   time, and any error class/message.
6. Log a structured summary.
7. Translate :class:`PaperWikiError` subclasses into stable exit codes.

The only public surface is :func:`run_digest` (async, testable) and the
Typer ``app`` (CLI wrapper). Tests monkeypatch
:func:`instantiate_pipeline` to inject stub plugins without exercising
the network.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from loguru import logger

from paperwiki._internal.dedup_ledger import (
    DedupLedgerEntry,
    append_dedup_entry,
)
from paperwiki._internal.logging import configure_runner_logging
from paperwiki._internal.run_status import RunStatusEntry, append_run_status
from paperwiki.config.recipe import (
    RecipeSchema,
    instantiate_pipeline,
    load_recipe,
)
from paperwiki.config.secrets import load_secrets_env
from paperwiki.core.errors import PaperWikiError
from paperwiki.core.models import Recommendation, RunContext

if TYPE_CHECKING:
    from paperwiki.core.pipeline import PipelineResult

app = typer.Typer(
    add_completion=False,
    help="Build a paper-wiki research digest from a recipe YAML.",
    no_args_is_help=True,
)


def _resolve_vault_path(recipe: RecipeSchema) -> Path | None:
    """Resolve the vault root from the recipe's obsidian reporter, if any.

    Per **D-O**, the run-status ledger is vault-bound — sync follows
    the vault, not the home directory. Recipes without an obsidian
    reporter (e.g. ``sources-only.yaml``) have no vault to anchor to,
    and the runner silently no-ops the ledger write rather than
    picking an arbitrary directory.

    Recipe authors who want a ledger but no Obsidian output can still
    add a stub obsidian reporter — the ledger only cares about the
    ``vault_path`` config value.
    """
    for spec in recipe.reporters:
        if spec.name == "obsidian":
            value = spec.config.get("vault_path")
            if isinstance(value, str | Path):
                return Path(value).expanduser()
    return None


def _extract_source_counts(counters: dict[str, int]) -> dict[str, int]:
    """Project ``source.<name>.fetched`` counters into ``{name: count}``."""
    result: dict[str, int] = {}
    for key, value in counters.items():
        if key.startswith("source.") and key.endswith(".fetched"):
            name = key[len("source.") : -len(".fetched")]
            result[name] = value
    return result


def _extract_source_errors(counters: dict[str, int]) -> dict[str, int]:
    """Project ``source.<name>.errors`` counters into ``{name: count}``."""
    result: dict[str, int] = {}
    for key, value in counters.items():
        if key.startswith("source.") and key.endswith(".errors"):
            name = key[len("source.") : -len(".errors")]
            result[name] = value
    return result


def _extract_filter_drops(counters: dict[str, int]) -> dict[str, int]:
    """Project ``filter.<name>.dropped`` counters into ``{name: count}``."""
    result: dict[str, int] = {}
    for key, value in counters.items():
        if key.startswith("filter.") and key.endswith(".dropped"):
            name = key[len("filter.") : -len(".dropped")]
            result[name] = value
    return result


def _record_dedup_surfaced(
    *,
    vault_path: Path | None,
    recipe_name: str,
    recommendations: list[Recommendation],
    when: datetime,
) -> None:
    """Append a ``surfaced`` row to the dedup ledger for every emitted paper.

    Per **D-F**, the ledger is the source of truth for "the user has
    seen this paper" — without this hook, the dedup filter would
    re-recommend the same paper on every digest run that has zero
    interaction with the vault's existing ``Wiki/sources/`` files.

    Failures (disk full, permissions) are logged and swallowed so
    ledger I/O never masks the underlying digest result.
    """
    if vault_path is None or not recommendations:
        return
    try:
        for rec in recommendations:
            entry = DedupLedgerEntry(
                timestamp=when,
                canonical_id=rec.paper.canonical_id,
                title=rec.paper.title,
                recipe=recipe_name,
                action="surfaced",
            )
            append_dedup_entry(vault_path, entry)
    except OSError as exc:
        logger.warning(
            "dedup_ledger.append.failed",
            vault=str(vault_path),
            error=str(exc),
        )


def _record_run_status(
    *,
    vault_path: Path | None,
    recipe_name: str,
    target_date: datetime,
    counters: dict[str, int],
    final_count: int,
    elapsed_ms: int,
    error: BaseException | None,
) -> None:
    """Append a run-status row when a vault is configured.

    Failures here (disk full, permissions error) are logged and
    swallowed so the user never gets blocked from seeing the digest by
    a ledger-write hiccup. The original exception (if any) is the
    caller's job to re-raise.
    """
    if vault_path is None:
        return
    try:
        entry = RunStatusEntry(
            timestamp=datetime.now(UTC),
            recipe=recipe_name,
            target_date=target_date,
            source_counts=_extract_source_counts(counters),
            source_errors=_extract_source_errors(counters),
            filter_drops=_extract_filter_drops(counters),
            final_count=final_count,
            elapsed_ms=elapsed_ms,
            error_class=type(error).__name__ if error is not None else None,
            error_message=str(error) if error is not None else None,
        )
        append_run_status(vault_path, entry)
    except OSError as ledger_exc:
        logger.warning(
            "run_status.append.failed",
            vault=str(vault_path),
            error=str(ledger_exc),
        )


async def run_digest(
    recipe_path: Path,
    target_date: datetime | None = None,
) -> int:
    """Run a digest from ``recipe_path`` and return a process exit code.

    ``target_date`` defaults to ``datetime.now(UTC)``. Tests inject
    explicit dates so output is deterministic.

    A run-status ledger row is appended on every code path that reaches
    the runner — successful runs, source-level errors (counted but not
    fatal), and hard exceptions during ``instantiate_pipeline`` /
    ``pipeline.run``. The append is best-effort; ledger I/O failures do
    not mask the underlying digest result.
    """
    effective_target = target_date or datetime.now(UTC)
    recipe = load_recipe(recipe_path)
    vault_path = _resolve_vault_path(recipe)

    start_ns = time.perf_counter_ns()
    ctx = RunContext(
        target_date=effective_target,
        config_snapshot={"recipe": recipe.name},
    )

    try:
        pipeline = instantiate_pipeline(recipe)
        result: PipelineResult = await pipeline.run(ctx, top_k=recipe.top_k)
    except PaperWikiError as exc:
        elapsed_ms = (time.perf_counter_ns() - start_ns) // 1_000_000
        _record_run_status(
            vault_path=vault_path,
            recipe_name=recipe.name,
            target_date=effective_target,
            counters=dict(ctx.counters),
            final_count=0,
            elapsed_ms=elapsed_ms,
            error=exc,
        )
        raise

    elapsed_ms = (time.perf_counter_ns() - start_ns) // 1_000_000
    _record_run_status(
        vault_path=vault_path,
        recipe_name=recipe.name,
        target_date=effective_target,
        counters=result.counters,
        final_count=len(result.recommendations),
        elapsed_ms=elapsed_ms,
        error=None,
    )
    # Task 9.168 / **D-F**: append ``surfaced`` rows so the next run's
    # dedup filter sees these papers and silently drops them. Recipes
    # without an obsidian vault (and therefore no ``vault_path``) skip
    # this hook — the ledger is vault-bound by design.
    _record_dedup_surfaced(
        vault_path=vault_path,
        recipe_name=recipe.name,
        recommendations=result.recommendations,
        when=datetime.now(UTC),
    )

    logger.info(
        "digest.complete",
        recipe=recipe.name,
        recommendations=len(result.recommendations),
        counters=result.counters,
    )
    return 0


def _parse_date(value: str) -> datetime:
    """Parse ``YYYY-MM-DD`` into a UTC-aware datetime, or raise typer.BadParameter."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError as exc:
        msg = f"invalid date {value!r}, expected YYYY-MM-DD"
        raise typer.BadParameter(msg) from exc


@app.command(name="digest")
def main(
    recipe: Annotated[
        Path,
        typer.Argument(
            help="Path to a recipe YAML file.",
            exists=False,  # let load_recipe() produce a clean UserError
        ),
    ],
    target_date: Annotated[
        str | None,
        typer.Option(
            "--target-date",
            help="YYYY-MM-DD; defaults to today (UTC).",
        ),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG-level logging."),
    ] = False,
) -> None:
    """Run a digest, exiting 0 on success or PaperWikiError.exit_code on failure."""
    configure_runner_logging(verbose=verbose)
    # Task 9.180 / D-U: auto-load $PAPERWIKI_HOME/secrets.env so a naked
    # `paperwiki digest` from a clean shell works without prior `source`.
    load_secrets_env()
    parsed_date = _parse_date(target_date) if target_date else None
    try:
        exit_code = asyncio.run(run_digest(recipe, parsed_date))
    except PaperWikiError as exc:
        # Surface the full user-facing message on stderr (Task 9.181 /
        # D-W). Loguru's default format treats ``error=str(exc)`` as a
        # hidden ``extra`` field; without an explicit echo the actionable
        # hint (e.g. ``/paper-wiki:migrate-recipe <path>`` from
        # ``RecipeSchemaError``) never reaches the user's terminal —
        # caught in v0.4.2 Phase A real-machine smoke. The structured
        # ``logger.error`` line is kept for log-aggregation tools.
        typer.echo(str(exc), err=True)
        logger.error("digest.failed", error=str(exc), exit_code=exc.exit_code)
        raise typer.Exit(exc.exit_code) from exc
    raise typer.Exit(exit_code)


if __name__ == "__main__":  # pragma: no cover - CLI entry
    app()


__all__ = ["app", "run_digest"]
