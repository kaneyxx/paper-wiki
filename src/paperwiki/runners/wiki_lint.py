"""``paperwiki.runners.wiki_lint`` — wiki health check.

Invoked by the ``paperwiki:wiki-lint`` SKILL via::

    ${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.wiki_lint <vault-path>

Reports five classes of issue, each with a stable code so SKILLs can
filter by severity and offer batch fixes:

================ ============================================================
Code             Meaning
================ ============================================================
ORPHAN_CONCEPT   Concept article with empty ``sources`` list.
STALE            ``last_synthesized`` older than ``stale_days`` (default 90).
OVERSIZED        Body exceeds ``max_lines`` (default 600).
BROKEN_LINK      ``[[target]]`` references a concept that doesn't exist.
STATUS_MISMATCH  ``status: reviewed`` paired with ``confidence < 0.5``.
================ ============================================================

Per SPEC §6, no LLM calls; the SKILL synthesizes the user-facing
narrative from this structured report.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated

import aiofiles
import typer
from loguru import logger

from paperwiki._internal.logging import configure_runner_logging
from paperwiki.config.layout import WIKI_SUBDIR
from paperwiki.core.errors import PaperWikiError
from paperwiki.plugins.backends.markdown_wiki import (
    ConceptSummary,
    MarkdownWikiBackend,
)

app = typer.Typer(
    add_completion=False,
    help="Health-check the wiki and emit a JSON report on stdout.",
    no_args_is_help=True,
)


_DEFAULT_STALE_DAYS = 90
_DEFAULT_MAX_LINES = 600
_REVIEWED_MIN_CONFIDENCE = 0.5
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")


@dataclass(frozen=True, slots=True)
class LintFinding:
    """A single lint issue."""

    severity: str  # info | warn | error
    code: str
    path: str
    message: str


@dataclass(slots=True)
class LintReport:
    """The combined output of a lint run."""

    findings: list[LintFinding] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=lambda: {"info": 0, "warn": 0, "error": 0})


async def lint_wiki(
    vault_path: Path,
    *,
    wiki_subdir: str = WIKI_SUBDIR,
    stale_days: int = _DEFAULT_STALE_DAYS,
    max_lines: int = _DEFAULT_MAX_LINES,
    now: datetime | None = None,
) -> LintReport:
    """Inspect the wiki and return structured findings."""
    backend = MarkdownWikiBackend(vault_path=vault_path, wiki_subdir=wiki_subdir)
    concepts = await backend.list_concepts()
    sources = await backend.list_sources()

    report = LintReport()

    # Wikilinks may target either a concept (by name) or a source file
    # (by file stem); both are valid resolution targets.
    known_targets = {c.name for c in concepts} | {s.path.stem for s in sources}
    when = now or datetime.now(UTC)
    cutoff = when.date() - timedelta(days=stale_days)

    for concept in concepts:
        await _check_concept(
            concept,
            vault_path=vault_path,
            cutoff_date=cutoff,
            max_lines=max_lines,
            known_concepts=known_targets,
            report=report,
        )

    # Sources that aren't referenced by any concept — "dangling".
    referenced_ids: set[str] = set()
    for concept in concepts:
        referenced_ids.update(concept.sources)
    for source in sources:
        if source.canonical_id and source.canonical_id not in referenced_ids:
            report.findings.append(
                LintFinding(
                    severity="info",
                    code="DANGLING_SOURCE",
                    path=str(source.path.relative_to(vault_path)),
                    message=(
                        f"Source {source.canonical_id!r} isn't referenced by any "
                        "concept; run /paper-wiki:wiki-ingest to fold it in."
                    ),
                )
            )

    for f in report.findings:
        report.counts[f.severity] = report.counts.get(f.severity, 0) + 1

    return report


# ---------------------------------------------------------------------------
# Per-concept rule checks
# ---------------------------------------------------------------------------


async def _check_concept(
    concept: ConceptSummary,
    *,
    vault_path: Path,
    cutoff_date: date,
    max_lines: int,
    known_concepts: set[str],
    report: LintReport,
) -> None:
    rel_path = str(concept.path.relative_to(vault_path))

    if not concept.sources:
        report.findings.append(
            LintFinding(
                severity="warn",
                code="ORPHAN_CONCEPT",
                path=rel_path,
                message="Concept article has no sources; ingest at least one paper.",
            )
        )

    if concept.status == "reviewed" and concept.confidence < _REVIEWED_MIN_CONFIDENCE:
        report.findings.append(
            LintFinding(
                severity="warn",
                code="STATUS_MISMATCH",
                path=rel_path,
                message=(
                    "status=reviewed but confidence < "
                    f"{_REVIEWED_MIN_CONFIDENCE}; either lower status or "
                    "raise confidence."
                ),
            )
        )

    body, last_synth = await _read_body_and_last_synth(concept.path)

    if last_synth is not None and last_synth < cutoff_date:
        report.findings.append(
            LintFinding(
                severity="info",
                code="STALE",
                path=rel_path,
                message=(
                    f"last_synthesized={last_synth.isoformat()} is older than"
                    f" cutoff {cutoff_date.isoformat()}; consider re-ingesting."
                ),
            )
        )

    line_count = body.count("\n") + 1
    if line_count > max_lines:
        report.findings.append(
            LintFinding(
                severity="info",
                code="OVERSIZED",
                path=rel_path,
                message=(f"{line_count} lines exceeds max_lines={max_lines}; split or summarize."),
            )
        )

    for target in _WIKILINK_RE.findall(body):
        if target.strip() not in known_concepts:
            report.findings.append(
                LintFinding(
                    severity="error",
                    code="BROKEN_LINK",
                    path=rel_path,
                    message=(f"[[{target.strip()}]] references a concept that doesn't exist."),
                )
            )


async def _read_body_and_last_synth(
    path: Path,
) -> tuple[str, date | None]:
    """Return (body, last_synthesized_date) for a concept file."""
    async with aiofiles.open(path, encoding="utf-8") as fh:
        text = await fh.read()
    last_synth: date | None = None
    body = text
    if body.startswith("---\n"):
        end = body.find("\n---\n", 4)
        if end > 0:
            front = body[4:end]
            body = body[end + 5 :]
            for line in front.splitlines():
                if line.startswith("last_synthesized:"):
                    raw = line.split(":", 1)[1].strip().strip('"').strip("'")
                    try:
                        last_synth = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=UTC).date()
                    except ValueError:
                        last_synth = None
    return body, last_synth


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@app.command()
def main(
    vault: Annotated[Path, typer.Argument(help="Path to the user's vault")],
    stale_days: Annotated[
        int, typer.Option("--stale-days", help="Threshold for STALE finding")
    ] = _DEFAULT_STALE_DAYS,
    max_lines: Annotated[
        int, typer.Option("--max-lines", help="Threshold for OVERSIZED finding")
    ] = _DEFAULT_MAX_LINES,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG-level logging."),
    ] = False,
) -> None:
    """Run wiki lint and emit a JSON report on stdout."""
    configure_runner_logging(verbose=verbose)
    try:
        report = asyncio.run(lint_wiki(vault, stale_days=stale_days, max_lines=max_lines))
    except PaperWikiError as exc:
        logger.error("wiki_lint.failed", error=str(exc))
        raise typer.Exit(exc.exit_code) from exc

    typer.echo(
        json.dumps(
            {
                "findings": [asdict(f) for f in report.findings],
                "counts": report.counts,
            },
            indent=2,
        )
    )


if __name__ == "__main__":  # pragma: no cover - CLI entry
    app()


__all__ = ["LintFinding", "LintReport", "app", "lint_wiki"]
