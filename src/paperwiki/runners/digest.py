"""``paperwiki.runners.digest`` — build a research digest from a recipe.

Invoked by the ``paperwiki:digest`` SKILL via::

    ${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.digest <recipe.yaml>

The runner is a thin shell:

1. Parse and validate the recipe YAML.
2. Instantiate the Pipeline.
3. Build a :class:`RunContext` (timezone-aware ``target_date``).
4. Run the pipeline.
5. Log a structured summary.
6. Translate :class:`PaperWikiError` subclasses into stable exit codes.

The only public surface is :func:`run_digest` (async, testable) and the
Typer ``app`` (CLI wrapper). Tests monkeypatch
:func:`instantiate_pipeline` to inject stub plugins without exercising
the network.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from loguru import logger

from paperwiki._internal.logging import configure_runner_logging
from paperwiki.config.recipe import instantiate_pipeline, load_recipe
from paperwiki.core.errors import PaperWikiError
from paperwiki.core.models import RunContext

app = typer.Typer(
    add_completion=False,
    help="Build a paper-wiki research digest from a recipe YAML.",
    no_args_is_help=True,
)


async def run_digest(
    recipe_path: Path,
    target_date: datetime | None = None,
) -> int:
    """Run a digest from ``recipe_path`` and return a process exit code.

    ``target_date`` defaults to ``datetime.now(UTC)``. Tests inject
    explicit dates so output is deterministic.
    """
    recipe = load_recipe(recipe_path)
    pipeline = instantiate_pipeline(recipe)

    ctx = RunContext(
        target_date=target_date or datetime.now(UTC),
        config_snapshot={"recipe": recipe.name},
    )

    result = await pipeline.run(ctx, top_k=recipe.top_k)
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
    parsed_date = _parse_date(target_date) if target_date else None
    try:
        exit_code = asyncio.run(run_digest(recipe, parsed_date))
    except PaperWikiError as exc:
        logger.error("digest.failed", error=str(exc), exit_code=exc.exit_code)
        raise typer.Exit(exc.exit_code) from exc
    raise typer.Exit(exit_code)


if __name__ == "__main__":  # pragma: no cover - CLI entry
    app()


__all__ = ["app", "run_digest"]
