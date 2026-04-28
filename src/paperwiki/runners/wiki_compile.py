"""``paperwiki.runners.wiki_compile`` — rebuild ``Wiki/index.md``.

Invoked by the ``paperwiki:wiki-compile`` SKILL via::

    ${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.wiki_compile <vault>

Walks the wiki via :class:`MarkdownWikiBackend`, sorts everything
deterministically, and rewrites ``Wiki/index.md`` with:

* Frontmatter recording the compile date and concept/source counts.
* A warning banner so users know hand-edits will be overwritten.
* A bullet list of concepts (wikilinked, with source counts and
  confidence).
* A table of sources (date, wikilinked title, listed concepts).

Per SPEC §6, no LLM calls; the SKILL paraphrases the result for the
user. The output is deterministic — same vault state produces the same
file bytes — so the file fits cleanly in version control.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import aiofiles
import typer
from loguru import logger

from paperwiki import __version__
from paperwiki._internal.locking import acquire_vault_lock
from paperwiki._internal.logging import configure_runner_logging
from paperwiki.config.layout import WIKI_SUBDIR
from paperwiki.core.errors import PaperWikiError
from paperwiki.plugins.backends.markdown_wiki import MarkdownWikiBackend

if TYPE_CHECKING:
    from paperwiki.plugins.backends.markdown_wiki import (
        ConceptSummary,
        SourceSummary,
    )


app = typer.Typer(
    add_completion=False,
    help="Rebuild Wiki/index.md from the current vault state.",
    no_args_is_help=True,
)


@dataclass(frozen=True, slots=True)
class CompileResult:
    """Summary returned by :func:`compile_wiki`."""

    index_path: Path
    concepts: int
    sources: int


async def compile_wiki(
    vault_path: Path,
    *,
    wiki_subdir: str = WIKI_SUBDIR,
    now: datetime | None = None,
) -> CompileResult:
    """Rebuild the wiki index file and return a summary.

    Acquires the vault advisory lock for the duration of the operation so
    concurrent ingest runs cannot observe a partial index.
    """
    async with acquire_vault_lock(vault_path):
        return await _compile_wiki_locked(vault_path, wiki_subdir=wiki_subdir, now=now)


async def _compile_wiki_locked(
    vault_path: Path,
    *,
    wiki_subdir: str = WIKI_SUBDIR,
    now: datetime | None = None,
) -> CompileResult:
    """Inner implementation — called with vault lock already held."""
    backend = MarkdownWikiBackend(vault_path=vault_path, wiki_subdir=wiki_subdir)
    sources = await backend.list_sources()
    concepts = await backend.list_concepts()

    # Sort deterministically.
    concepts_sorted = sorted(concepts, key=lambda c: c.title.lower())
    sources_sorted = sorted(sources, key=lambda s: s.canonical_id.lower())

    when = now or datetime.now(UTC)
    body = _render_index(concepts_sorted, sources_sorted, when=when)

    index_path = vault_path / wiki_subdir / "index.md"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(index_path, "w", encoding="utf-8") as fh:
        await fh.write(body)

    return CompileResult(
        index_path=index_path,
        concepts=len(concepts_sorted),
        sources=len(sources_sorted),
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_index(
    concepts: list[ConceptSummary],
    sources: list[SourceSummary],
    *,
    when: datetime,
) -> str:
    parts: list[str] = []
    parts.append(_render_frontmatter(len(concepts), len(sources), when))
    parts.append(
        "# Wiki Index\n\n"
        "_Auto-generated. Edit at your own risk; "
        "`/paper-wiki:wiki-compile` overwrites this file._\n"
    )

    if concepts:
        parts.append("## Concepts\n")
        parts.extend(
            f"- [[{c.name}]] — {len(c.sources)} sources, confidence {c.confidence:.2f}"
            for c in concepts
        )
        parts.append("")
    else:
        parts.append("## Concepts\n\n_No concepts yet._\n")

    if sources:
        parts.append("## Sources\n")
        # Inverted index: which concepts list each source.
        by_source: dict[str, list[str]] = {}
        for concept in concepts:
            for src_id in concept.sources:
                by_source.setdefault(src_id, []).append(concept.name)
        parts.append("| Date | Source | Concepts |")
        parts.append("| ---- | ------ | -------- |")
        for source in sources:
            stem = source.path.stem
            concept_links = (
                ", ".join(f"[[{name}]]" for name in sorted(by_source.get(source.canonical_id, [])))
                or "—"
            )
            parts.append(f"| {when.strftime('%Y-%m-%d')} | [[{stem}]] | {concept_links} |")
        parts.append("")
    else:
        parts.append("## Sources\n\n_No sources yet._\n")

    return "\n".join(parts) + "\n"


def _render_frontmatter(
    concept_count: int,
    source_count: int,
    when: datetime,
) -> str:
    return (
        "---\n"
        f'generated_by: "paper-wiki/{__version__}"\n'
        f'last_compiled: "{when.strftime("%Y-%m-%d")}"\n'
        f"concepts: {concept_count}\n"
        f"sources: {source_count}\n"
        "---\n"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@app.command()
def main(
    vault: Annotated[Path, typer.Argument(help="Path to the user's vault")],
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG-level logging."),
    ] = False,
) -> None:
    """Rebuild Wiki/index.md and print a one-line summary."""
    configure_runner_logging(verbose=verbose)
    try:
        result = asyncio.run(compile_wiki(vault))
    except PaperWikiError as exc:
        logger.error("wiki_compile.failed", error=str(exc))
        raise typer.Exit(exc.exit_code) from exc

    typer.echo(
        f"compiled: {result.concepts} concepts, {result.sources} sources -> {result.index_path}"
    )


if __name__ == "__main__":  # pragma: no cover - CLI entry
    app()


__all__ = ["CompileResult", "app", "compile_wiki"]
