"""``paperwiki.runners.wiki_ingest_plan`` — list concepts affected by a new source.

Invoked by the ``paperwiki:wiki-ingest`` SKILL via::

    ${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.wiki_ingest_plan \
        <vault-path> <canonical-id>

Returns a JSON ``IngestPlan`` describing:

* whether the source exists in the wiki,
* which existing concept articles already reference it (and therefore
  need re-synthesis),
* suggested concept names — pulled from the source's ``related_concepts``
  frontmatter — that aren't yet concepts in the wiki.

When ``--auto-bootstrap`` is set, the runner also:

1. Creates a stub file for every suggested-but-missing concept using the
   sentinel body and frontmatter from ``paperwiki.runners._stub_constants``.
2. Re-inspects the wiki so the freshly-stubbed concepts appear in
   ``affected_concepts`` (they now exist and reference the source).
3. Returns both ``created_stubs`` (new concept names written this run) and
   ``affected_concepts`` (all concepts that reference the source, including
   the just-stubbed ones).

The runner does not regenerate any prose. The SKILL reads this plan,
fetches the source, walks the affected concepts, asks Claude to update
each one, and writes back through ``MarkdownWikiBackend.upsert_concept``.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import aiofiles
import typer
import yaml
from loguru import logger

from paperwiki._internal.locking import acquire_vault_lock
from paperwiki._internal.logging import configure_runner_logging
from paperwiki.config.layout import WIKI_SUBDIR
from paperwiki.core.errors import PaperWikiError
from paperwiki.plugins.backends.markdown_wiki import MarkdownWikiBackend
from paperwiki.runners._stub_constants import (
    AUTO_CREATED_CONFIDENCE,
    AUTO_CREATED_FLAG,
    AUTO_CREATED_SENTINEL_BODY,
    AUTO_CREATED_STATUS,
    AUTO_CREATED_TAGS,
)

app = typer.Typer(
    add_completion=False,
    help="List concepts affected by a new source; emit JSON plan on stdout.",
    no_args_is_help=True,
)


_WIKILINK_TARGET_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")


@dataclass(frozen=True, slots=True)
class IngestPlan:
    """The plan returned for one source-id."""

    source_id: str
    source_exists: bool
    affected_concepts: list[str] = field(default_factory=list)
    suggested_concepts: list[str] = field(default_factory=list)
    created_stubs: list[str] = field(default_factory=list)
    folded_citations: list[str] = field(default_factory=list)


async def plan_ingest(
    vault_path: Path,
    source_id: str,
    *,
    wiki_subdir: str = WIKI_SUBDIR,
    auto_bootstrap: bool = False,
) -> IngestPlan:
    """Inspect the wiki and return the ingest plan for ``source_id``.

    When ``auto_bootstrap`` is ``True``, any concept names in
    ``suggested_concepts`` that do not yet exist on disk are written as
    stub files before the affected-concept query is re-run. This ensures
    a fresh vault does not dead-end with an empty ``affected_concepts``
    list on the first ingest.

    Acquires the vault advisory lock for the duration of the operation so
    concurrent ingest or compile runs cannot observe partial state.
    """
    async with acquire_vault_lock(vault_path):
        return await _plan_ingest_locked(
            vault_path,
            source_id,
            wiki_subdir=wiki_subdir,
            auto_bootstrap=auto_bootstrap,
        )


async def _plan_ingest_locked(
    vault_path: Path,
    source_id: str,
    *,
    wiki_subdir: str = WIKI_SUBDIR,
    auto_bootstrap: bool = False,
) -> IngestPlan:
    """Inner implementation — called with vault lock already held."""
    backend = MarkdownWikiBackend(vault_path=vault_path, wiki_subdir=wiki_subdir)
    sources = await backend.list_sources()
    concepts = await backend.list_concepts()

    source = next((s for s in sources if s.canonical_id == source_id), None)
    # Use ``title`` (the human-facing name) rather than ``name`` (file stem)
    # so the SKILL can pass the value back into upsert_concept directly.
    affected = [c.title for c in concepts if source_id in c.sources]

    if source is None:
        return IngestPlan(
            source_id=source_id,
            source_exists=False,
            affected_concepts=affected,
            suggested_concepts=[],
            created_stubs=[],
        )

    existing_by_lower: dict[str, str] = {c.title.lower(): c.title for c in concepts}
    existing_names = set(existing_by_lower)
    suggested: list[str] = []
    seen: set[str] = set()
    for raw in source.related_concepts:
        clean = _extract_wikilink_target(raw)
        if not clean:
            continue
        key = clean.lower()
        if key in existing_names or key in seen:
            continue
        seen.add(key)
        suggested.append(clean)

    created_stubs: list[str] = []

    folded_citations: list[str] = []

    if auto_bootstrap:
        # Compute all concept names the source hints at, whether or not
        # they already exist on disk.
        all_hinted: list[str] = []
        seen_all: set[str] = set()
        for raw in source.related_concepts:
            clean = _extract_wikilink_target(raw)
            if not clean:
                continue
            key = clean.lower()
            if key in seen_all:
                continue
            seen_all.add(key)
            all_hinted.append(clean)

        # Concepts in all_hinted that do NOT yet exist → stub them.
        missing = [n for n in all_hinted if n.lower() not in existing_names]
        # Concepts in all_hinted that DO exist → fold the citation in atomically.
        pre_existing = [n for n in all_hinted if n.lower() in existing_names]

        if missing:
            created_stubs = await _bootstrap_missing_concepts(
                backend=backend,
                concept_names=missing,
                source_id=source_id,
            )

        if pre_existing:
            folded_citations = await _fold_citations(
                backend=backend,
                concept_names=pre_existing,
                source_id=source_id,
            )

        # Re-query so freshly-stubbed and freshly-folded concepts appear in affected.
        concepts = await backend.list_concepts()
        affected = [c.title for c in concepts if source_id in c.sources]

    return IngestPlan(
        source_id=source_id,
        source_exists=True,
        affected_concepts=sorted(affected),
        suggested_concepts=suggested,
        created_stubs=created_stubs,
        folded_citations=sorted(folded_citations),
    )


async def _read_concept(path: Path) -> tuple[dict[str, object], str]:
    """Return (frontmatter_dict, body_str) for an existing concept file."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text
    end_idx = text.index("\n---\n", 4)
    fm_text = text[4:end_idx]
    body = text[end_idx + 5 :]  # skip past "\n---\n"
    return yaml.safe_load(fm_text) or {}, body


async def _write_concept(path: Path, frontmatter: dict[str, object], body: str) -> None:
    """Write back with frontmatter + body verbatim."""
    rendered = (
        "---\n" + yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True) + "---\n" + body
    )
    async with aiofiles.open(path, "w", encoding="utf-8") as fh:
        await fh.write(rendered)


async def _fold_citations(
    *,
    backend: MarkdownWikiBackend,
    concept_names: list[str],
    source_id: str,
) -> list[str]:
    """For each name in concept_names that EXISTS on disk, append source_id to
    its ``sources`` list (idempotent) and bump ``last_synthesized`` to today.

    Returns the list of concept names that were actually updated (i.e. source_id
    was not already present).
    """
    folded: list[str] = []
    for name in concept_names:
        concept_path = backend._concept_path(name)
        if not concept_path.exists():
            continue
        frontmatter, body = await _read_concept(concept_path)
        raw_sources = frontmatter.get("sources")
        sources: list[str] = [
            str(s) for s in (raw_sources if isinstance(raw_sources, list) else [])
        ]
        if source_id in sources:
            continue  # idempotent — already present, skip
        sources.append(source_id)
        frontmatter["sources"] = sources
        frontmatter["last_synthesized"] = _today_utc()
        await _write_concept(concept_path, frontmatter, body)
        folded.append(name)
    return folded


async def _bootstrap_missing_concepts(
    *,
    backend: MarkdownWikiBackend,
    concept_names: list[str],
    source_id: str,
) -> list[str]:
    """Write stub files for each name in ``concept_names``.

    Returns the list of names that were actually written (skips any that
    already exist on disk, which should not happen in practice since the
    caller filters by existing_names, but guards against races).
    """
    created: list[str] = []
    for name in concept_names:
        concept_path = backend._concept_path(name)
        if concept_path.exists():
            continue
        concept_path.parent.mkdir(parents=True, exist_ok=True)
        frontmatter: dict[str, object] = {
            "title": name,
            "status": AUTO_CREATED_STATUS,
            "confidence": round(AUTO_CREATED_CONFIDENCE, 4),
            "sources": [source_id],
            "related_concepts": [],
            "auto_created": AUTO_CREATED_FLAG,
            "tags": list(AUTO_CREATED_TAGS),
            "last_synthesized": _today_utc(),
        }
        rendered = (
            "---\n"
            + yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
            + "---\n\n"
            + AUTO_CREATED_SENTINEL_BODY
            + "\n"
        )
        async with aiofiles.open(concept_path, "w", encoding="utf-8") as fh:
            await fh.write(rendered)

        created.append(name)

    return created


def _today_utc() -> str:
    """Return today's UTC date as ``YYYY-MM-DD``."""
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _extract_wikilink_target(value: str) -> str:
    """Pull the link target out of a ``[[target]]`` or ``[[target|label]]`` entry.

    Falls back to the input string with surrounding brackets stripped if
    the regex doesn't match.
    """
    match = _WIKILINK_TARGET_RE.search(value)
    if match:
        return match.group(1).strip()
    return value.strip("[]").split("|")[0].strip()


@app.command(name="wiki-ingest")
def main(
    vault: Annotated[Path, typer.Argument(help="Path to the user's vault")],
    source_id: Annotated[str, typer.Argument(help="Canonical id, e.g. arxiv:2506.13063")],
    auto_bootstrap: Annotated[
        bool,
        typer.Option(
            "--auto-bootstrap/--no-auto-bootstrap",
            help=(
                "When set, auto-create stub concept files for every suggested-but-missing "
                "concept before the update loop runs. For use by the digest auto-chain only; "
                "do not pass for interactive /paper-wiki:wiki-ingest invocations."
            ),
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG-level logging."),
    ] = False,
) -> None:
    """Run the ingest plan and emit JSON on stdout."""
    configure_runner_logging(verbose=verbose)
    try:
        plan = asyncio.run(plan_ingest(vault, source_id, auto_bootstrap=auto_bootstrap))
    except PaperWikiError as exc:
        logger.error("wiki_ingest_plan.failed", error=str(exc))
        raise typer.Exit(exc.exit_code) from exc

    typer.echo(json.dumps(asdict(plan), indent=2))


if __name__ == "__main__":  # pragma: no cover - CLI entry
    app()


__all__ = ["IngestPlan", "app", "plan_ingest"]
