"""``paperwiki dedup-dismiss`` — manually drop a paper from future digests.

Appends a ``dismissed`` row to
``<vault>/.paperwiki/dedup-ledger.jsonl`` (task 9.168 / **D-F**) so
the dedup filter silently drops the paper on every subsequent run.

Pair with ``paperwiki dedup-list`` to audit dismissals and
``paperwiki gc-dedup-ledger`` to prune ancient rows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from loguru import logger

from paperwiki._internal.dedup_ledger import (
    DedupLedgerEntry,
    append_dedup_entry,
)
from paperwiki._internal.logging import configure_runner_logging
from paperwiki.config.vault_resolver import resolve_vault
from paperwiki.core.errors import UserError

app = typer.Typer(
    add_completion=False,
    help="Append a 'dismissed' row to the vault's dedup ledger.",
    no_args_is_help=True,
)


@app.command(name="dedup-dismiss")
def main(
    canonical_id: Annotated[
        str,
        typer.Argument(
            help="Paper id in `<source>:<id>` form, e.g. `arxiv:2401.12345`.",
        ),
    ],
    title: Annotated[
        str,
        typer.Option(
            "--title",
            help="Paper title — used for title-key dedup when canonical ids drift.",
        ),
    ],
    vault: Annotated[
        Path | None,
        typer.Option(
            "--vault",
            help=(
                "Path to the Obsidian vault that owns the dedup ledger. "
                "Optional (Task 9.195 / D-V) — falls back to "
                "$PAPERWIKI_DEFAULT_VAULT, then "
                "~/.config/paper-wiki/config.toml::default_vault."
            ),
            show_default=False,
        ),
    ] = None,
    recipe: Annotated[
        str,
        typer.Option(
            "--recipe",
            help="Recipe-of-origin; defaults to 'manual' for ad-hoc dismissals.",
        ),
    ] = "manual",
    reason: Annotated[
        str | None,
        typer.Option(
            "--reason",
            help="Optional human-readable reason recorded in the ledger.",
        ),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG-level logging."),
    ] = False,
) -> None:
    """Append a dismissed-row to the dedup ledger and exit 0."""
    configure_runner_logging(verbose=verbose)
    if vault is None:
        try:
            vault = resolve_vault(None)
        except UserError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(exc.exit_code) from exc
    entry = DedupLedgerEntry(
        timestamp=datetime.now(UTC),
        canonical_id=canonical_id,
        title=title,
        recipe=recipe,
        action="dismissed",
        reason=reason,
    )
    append_dedup_entry(vault.expanduser(), entry)
    typer.echo(f"dismissed {canonical_id} in {vault / '.paperwiki' / 'dedup-ledger.jsonl'}")
    logger.info(
        "dedup_dismiss.complete",
        canonical_id=canonical_id,
        vault=str(vault),
        reason=reason,
    )


if __name__ == "__main__":  # pragma: no cover - CLI entry
    app()


__all__ = ["app", "main"]
