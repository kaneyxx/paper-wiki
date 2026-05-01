"""``paperwiki gc-dedup-ledger`` — prune the persistent dedup ledger.

Exposes :func:`paperwiki._internal.dedup_ledger.gc_old_entries` to
end-users so they can drop ancient rows after a keyword pivot or a
vault reorganisation. By default the runner honors
``PAPERWIKI_DEDUP_LEDGER_KEEP`` (or 365 days when unset) so calling
``paperwiki gc-dedup-ledger --vault <path>`` with no flags has
predictable semantics on every machine.

This runner is the manual sweep — paper-wiki does NOT auto-run gc
on every digest because (a) the ledger is small (one line per
emit), (b) the user might prefer to pin retention to their backup
cadence, and (c) silent state mutation during a digest run violates
the "the digest is the only thing that writes the digest" contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from loguru import logger

from paperwiki._internal.dedup_ledger import gc_old_entries
from paperwiki._internal.logging import configure_runner_logging

app = typer.Typer(
    add_completion=False,
    help="Prune <vault>/.paperwiki/dedup-ledger.jsonl entries older than --keep-days.",
    no_args_is_help=True,
)


@app.command(name="gc-dedup-ledger")
def main(
    vault: Annotated[
        Path,
        typer.Option(
            "--vault",
            help="Path to the Obsidian vault that owns the dedup ledger.",
        ),
    ],
    keep_days: Annotated[
        int | None,
        typer.Option(
            "--keep-days",
            help=(
                "Drop entries older than this many days. Defaults to "
                "PAPERWIKI_DEDUP_LEDGER_KEEP (or 365)."
            ),
        ),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG-level logging."),
    ] = False,
) -> None:
    """Prune ledger rows older than ``--keep-days`` and print the count."""
    configure_runner_logging(verbose=verbose)
    deleted = gc_old_entries(vault.expanduser(), keep_days=keep_days)
    typer.echo(f"deleted {deleted} entries")
    logger.info("gc_dedup_ledger.complete", vault=str(vault), deleted=deleted)


if __name__ == "__main__":  # pragma: no cover - CLI entry
    app()


__all__ = ["app", "main"]
