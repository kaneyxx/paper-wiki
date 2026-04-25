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

The runner does not regenerate any prose. The SKILL reads this plan,
fetches the source, walks the affected concepts, asks Claude to update
each one, and writes back through ``MarkdownWikiBackend.upsert_concept``.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Annotated

import typer
from loguru import logger

from paperwiki.config.layout import WIKI_SUBDIR
from paperwiki.core.errors import PaperWikiError
from paperwiki.plugins.backends.markdown_wiki import MarkdownWikiBackend

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


async def plan_ingest(
    vault_path: Path,
    source_id: str,
    *,
    wiki_subdir: str = WIKI_SUBDIR,
) -> IngestPlan:
    """Inspect the wiki and return the ingest plan for ``source_id``."""
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
        )

    existing_names = {c.title.lower() for c in concepts}
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

    return IngestPlan(
        source_id=source_id,
        source_exists=True,
        affected_concepts=sorted(affected),
        suggested_concepts=suggested,
    )


def _extract_wikilink_target(value: str) -> str:
    """Pull the link target out of a ``[[target]]`` or ``[[target|label]]`` entry.

    Falls back to the input string with surrounding brackets stripped if
    the regex doesn't match.
    """
    match = _WIKILINK_TARGET_RE.search(value)
    if match:
        return match.group(1).strip()
    return value.strip("[]").split("|")[0].strip()


@app.command()
def main(
    vault: Annotated[Path, typer.Argument(help="Path to the user's vault")],
    source_id: Annotated[str, typer.Argument(help="Canonical id, e.g. arxiv:2506.13063")],
) -> None:
    """Run the ingest plan and emit JSON on stdout."""
    try:
        plan = asyncio.run(plan_ingest(vault, source_id))
    except PaperWikiError as exc:
        logger.error("wiki_ingest_plan.failed", error=str(exc))
        raise typer.Exit(exc.exit_code) from exc

    typer.echo(json.dumps(asdict(plan), indent=2))


if __name__ == "__main__":  # pragma: no cover - CLI entry
    app()


__all__ = ["IngestPlan", "app", "plan_ingest"]
