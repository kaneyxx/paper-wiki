"""``paperwiki recipe-validate`` — strict schema check for a recipe (task 9.170).

Recipe authors run this before committing or shipping a YAML to a
shared location to catch typos, missing required fields, and out-of-range
values without having to invoke the full ``paperwiki digest`` pipeline.
The runner exits 0 on a clean recipe, 1 on any validation failure, so
editors can wire it into save hooks (e.g. an Obsidian template "save +
validate" workflow).

The error format mirrors ``paperwiki.config.recipe.load_recipe`` —
field path + reason for each violation, one per line. YAML-syntax
errors carry line + column so the user can jump straight to the
offending character.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from loguru import logger

from paperwiki._internal.logging import configure_runner_logging
from paperwiki.config.recipe import load_recipe
from paperwiki.core.errors import UserError

app = typer.Typer(
    add_completion=False,
    help="Validate a recipe YAML against the v0.4.x schema.",
    no_args_is_help=True,
)


@app.command(name="recipe-validate")
def main(
    recipe: Annotated[
        Path,
        typer.Argument(
            help="Path to the recipe YAML to validate.",
        ),
    ],
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG-level logging."),
    ] = False,
) -> None:
    """Validate ``recipe`` and exit 0 on success, 1 on failure."""
    configure_runner_logging(verbose=verbose)
    try:
        validated = load_recipe(recipe.expanduser())
    except UserError as exc:
        typer.echo(str(exc), err=True)
        logger.error("recipe_validate.failed", path=str(recipe))
        raise typer.Exit(1) from exc
    typer.echo(f"ok: {recipe} validates as recipe {validated.name!r}")


if __name__ == "__main__":  # pragma: no cover - CLI entry
    app()


__all__ = ["app", "main"]
