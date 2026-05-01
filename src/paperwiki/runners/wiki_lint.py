"""``paperwiki.runners.wiki_lint`` — wiki health check.

Invoked by the ``paperwiki:wiki-lint`` SKILL via::

    ${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.wiki_lint <vault-path>

Reports issues with stable codes so SKILLs can filter by severity and
offer batch fixes:

==================== =======================================================
Code                 Meaning
==================== =======================================================
ORPHAN_CONCEPT       Concept article with empty ``sources`` list.
STALE                ``last_synthesized`` older than ``stale_days``.
OVERSIZED            Body exceeds ``max_lines`` (default 600).
BROKEN_LINK          ``[[target]]`` references a concept that doesn't exist.
STATUS_MISMATCH      ``status: reviewed`` paired with ``confidence < 0.5``.
DANGLING_SOURCE      Source not referenced by any concept.
ORPHAN_SOURCE [#]_   v0.4.x typed Concept/Topic with no inbound wikilinks.
GRAPH_INCONSISTENT   v0.4.x edges.jsonl claims A→B but B's frontmatter
                     ``references:`` is present and does not list A.
==================== =======================================================

.. [#] ORPHAN_SOURCE + GRAPH_INCONSISTENT are v0.4.x graph-layer rules
   gated behind ``--check-graph`` (default off). They consume the
   typed-subdir layout (D-I) and the ``.graph/`` sidecar (D-B) added in
   tasks 9.156 / 9.157.

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
from paperwiki.runners.wiki_compile_graph import (
    EDGES_FILENAME,
    GRAPH_SUBDIR,
    ParsedEntity,
    iter_edges_jsonl,
    walk_entities,
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
    check_graph: bool = False,
) -> LintReport:
    """Inspect the wiki and return structured findings.

    When ``check_graph=True``, also runs the v0.4.x graph-layer rules
    (ORPHAN_SOURCE + GRAPH_INCONSISTENT) over the typed-subdir layout
    plus the ``.graph/`` sidecar. Default off so existing pre-v0.4.x
    vaults don't surface new findings on upgrade.
    """
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

    if check_graph:
        _check_graph_layer(vault_path, wiki_subdir, report)

    for f in report.findings:
        report.counts[f.severity] = report.counts.get(f.severity, 0) + 1

    return report


# ---------------------------------------------------------------------------
# v0.4.x graph-layer rules (task 9.158, opt-in via --check-graph)
# ---------------------------------------------------------------------------


def _check_graph_layer(
    vault_path: Path,
    wiki_subdir: str,
    report: LintReport,
) -> None:
    """Append ORPHAN_SOURCE + GRAPH_INCONSISTENT findings to ``report``.

    See module docstring for rule semantics.
    """
    wiki_root = vault_path / wiki_subdir
    if not wiki_root.is_dir():
        # Pre-v0.4.x layout (no typed subdirs) — nothing to check.
        return
    entities = walk_entities(wiki_root)
    if not entities:
        return

    # Build alias → entity_id resolution map (mirrors wiki_compile_graph)
    # so we can resolve body wikilinks to concrete entity ids.
    alias_to_id: dict[str, str] = {}
    by_id: dict[str, ParsedEntity] = {}
    for entity in entities:
        by_id[entity.entity_id] = entity
        for alias in entity.aliases:
            alias_to_id.setdefault(alias, entity.entity_id)

    # Build inbound-reference index: dst_id -> set of src_ids that link.
    inbound: dict[str, set[str]] = {}
    for entity in entities:
        for raw in entity.body_wikilinks:
            target = raw.strip()
            resolved = alias_to_id.get(target)
            if resolved is None or resolved == entity.entity_id:
                continue
            inbound.setdefault(resolved, set()).add(entity.entity_id)

    # ORPHAN_SOURCE — concepts/topics with no inbound wikilinks. Papers
    # and people are exempt: papers can be standalone leaves, and people
    # records are anchored by metadata, not graph reachability.
    for entity in entities:
        if entity.entity_type not in ("concepts", "topics"):
            continue
        if not inbound.get(entity.entity_id):
            report.findings.append(
                LintFinding(
                    severity="warn",
                    code="ORPHAN_SOURCE",
                    path=f"{entity.entity_id}.md",
                    message=(
                        f"{entity.entity_type[:-1].title()} {entity.entity_id!r} "
                        "has no inbound wikilinks; either link it from a "
                        "paper/topic or remove the orphan note."
                    ),
                )
            )

    # GRAPH_INCONSISTENT — only fires when an entity's frontmatter
    # *declares* a ``references:`` field; missing field = no claim made.
    edges_path = wiki_root / GRAPH_SUBDIR / EDGES_FILENAME
    if not edges_path.exists():
        return
    for edge in iter_edges_jsonl(edges_path):
        dst_entity = by_id.get(edge.dst)
        if dst_entity is None:
            continue
        declared_refs = dst_entity.frontmatter.get("references")
        if declared_refs is None:
            # User has not declared a refs list — no inconsistency to flag.
            continue
        if not isinstance(declared_refs, list):
            continue
        # Edge ``src`` is an entity_id (papers/<slug>); also accept the
        # bare slug + canonical_id alias forms when matching against the
        # declared list, so users have flexibility in how they author refs.
        src_aliases = {edge.src}
        src_entity = by_id.get(edge.src)
        if src_entity is not None:
            src_aliases |= src_entity.aliases
        if not any(ref in src_aliases for ref in declared_refs):
            report.findings.append(
                LintFinding(
                    severity="warn",
                    code="GRAPH_INCONSISTENT",
                    path=f"{edge.dst}.md",
                    message=(
                        f"edges.jsonl records {edge.src!r} → {edge.dst!r} but "
                        f"{edge.dst!r}'s frontmatter ``references:`` does not "
                        f"list it; either add it to references or remove the "
                        f"originating wikilink."
                    ),
                )
            )


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


@app.command(name="wiki-lint")
def main(
    vault: Annotated[Path, typer.Argument(help="Path to the user's vault")],
    wiki_subdir: Annotated[
        str,
        typer.Option(
            "--wiki-subdir",
            help="Subdir under the vault holding the wiki notes.",
        ),
    ] = WIKI_SUBDIR,
    stale_days: Annotated[
        int, typer.Option("--stale-days", help="Threshold for STALE finding")
    ] = _DEFAULT_STALE_DAYS,
    max_lines: Annotated[
        int, typer.Option("--max-lines", help="Threshold for OVERSIZED finding")
    ] = _DEFAULT_MAX_LINES,
    check_graph: Annotated[
        bool,
        typer.Option(
            "--check-graph",
            help=("Run v0.4.x graph-layer rules (ORPHAN_SOURCE, GRAPH_INCONSISTENT)."),
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG-level logging."),
    ] = False,
) -> None:
    """Run wiki lint and emit a JSON report on stdout."""
    configure_runner_logging(verbose=verbose)
    try:
        report = asyncio.run(
            lint_wiki(
                vault,
                wiki_subdir=wiki_subdir,
                stale_days=stale_days,
                max_lines=max_lines,
                check_graph=check_graph,
            )
        )
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
