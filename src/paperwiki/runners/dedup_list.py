"""``paperwiki dedup-list`` — audit the dedup ledger.

Surfaces every ``dismissed`` row from
``<vault>/.paperwiki/dedup-ledger.jsonl`` (task 9.168 / **D-F**) so the
user can review what their past selves have rejected. Useful for:

* re-evaluating a paper after a recipe pivot ("did I dismiss this
  too aggressively?")
* spotting heuristic drift ("the last 30 papers I dismissed all
  had the same flagged keyword")
* preparing a reset (``--keep-days 0`` on ``gc-dedup-ledger``)

Output formats:

* ``--pretty`` (default) — Markdown table for human reading.
* ``--json`` — JSONL stream of :class:`DedupLedgerEntry` rows for
  scripts and SKILL pipes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from loguru import logger

from paperwiki._internal.dedup_ledger import (
    DedupLedgerEntry,
    read_dismissed_entries,
)
from paperwiki._internal.logging import configure_runner_logging

app = typer.Typer(
    add_completion=False,
    help="List ``dismissed`` rows from <vault>/.paperwiki/dedup-ledger.jsonl.",
    no_args_is_help=True,
)


def _render_pretty(entries: list[DedupLedgerEntry]) -> str:
    if not entries:
        return "(no dismissed papers)"
    lines = [
        "| dismissed (UTC)     | canonical_id | recipe | reason |",
        "|---------------------|--------------|--------|--------|",
    ]
    for entry in entries:
        when = entry.timestamp.strftime("%Y-%m-%d %H:%M")
        reason = entry.reason or "—"
        lines.append(f"| {when} | {entry.canonical_id} | {entry.recipe} | {reason} |")
    return "\n".join(lines)


def _render_json(entries: list[DedupLedgerEntry]) -> str:
    return "\n".join(json.dumps(json.loads(e.model_dump_json())) for e in entries)


@app.command(name="dedup-list")
def main(
    vault: Annotated[
        Path,
        typer.Option(
            "--vault",
            help="Path to the Obsidian vault that owns the dedup ledger.",
        ),
    ],
    output_format: Annotated[
        str,
        typer.Option(
            "--format",
            help="Output format: 'pretty' (Markdown table) or 'json' (JSONL).",
        ),
    ] = "pretty",
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG-level logging."),
    ] = False,
) -> None:
    """Print every dismissed entry in the dedup ledger."""
    configure_runner_logging(verbose=verbose)
    entries = read_dismissed_entries(vault.expanduser())
    if output_format == "json":
        typer.echo(_render_json(entries))
    elif output_format == "pretty":
        typer.echo(_render_pretty(entries))
    else:
        msg = f"unknown format {output_format!r}; expected 'pretty' or 'json'"
        raise typer.BadParameter(msg)
    logger.info("dedup_list.complete", vault=str(vault), entries=len(entries))


if __name__ == "__main__":  # pragma: no cover - CLI entry
    app()


__all__ = ["app", "main"]
