"""``paperwiki.runners.wiki_query`` — keyword search across the wiki.

Invoked by the ``paperwiki:wiki-query`` SKILL via::

    ${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.wiki_query \
        <vault-path> <query>

Emits a JSON array of ``WikiHit`` records on stdout, ranked by a tiny
TF-IDF-ish score: title hits outweigh tag hits, concepts get a small
boost per backing source. Per SPEC §6, this runner does not call any
LLM — the SKILL synthesizes the answer afterward, citing returned hits.

We deliberately use plain substring + token matching rather than vector
embeddings; at the ~100-source scale the wiki is built for, that is
enough and avoids embedding infrastructure (Karpathy's gist, see
``tasks/plan.md`` Appendix A).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated

import aiofiles
import typer
from loguru import logger

from paperwiki._internal.logging import configure_runner_logging
from paperwiki.config.layout import WIKI_SUBDIR
from paperwiki.core.errors import PaperWikiError
from paperwiki.plugins.backends.markdown_wiki import MarkdownWikiBackend

app = typer.Typer(
    add_completion=False,
    help="Keyword-search the wiki and emit ranked hits as JSON.",
    no_args_is_help=True,
)


@dataclass(frozen=True, slots=True)
class WikiHit:
    """One ranked search result."""

    type: str  # "source" | "concept"
    path: str
    title: str
    snippet: str
    score: float


# Score weights — title beats tag/related-concept beats source-link.
_TITLE_WEIGHT = 2.0
_TAG_WEIGHT = 1.0
_CONCEPT_SOURCE_BONUS = 0.1
_SNIPPET_MAX = 200


async def query_wiki(
    vault_path: Path,
    query: str,
    *,
    top_k: int = 10,
    wiki_subdir: str = WIKI_SUBDIR,
) -> list[WikiHit]:
    """Search the vault's wiki for ``query``; return up to ``top_k`` hits."""
    terms = [t for t in query.lower().split() if t]
    if not terms:
        return []

    backend = MarkdownWikiBackend(vault_path=vault_path, wiki_subdir=wiki_subdir)
    sources = await backend.list_sources()
    concepts = await backend.list_concepts()

    hits: list[WikiHit] = []

    for source in sources:
        score = _score_match(terms, source.title, source.tags)
        if score <= 0:
            continue
        hits.append(
            WikiHit(
                type="source",
                path=str(source.path.relative_to(vault_path)),
                title=source.title,
                snippet=source.title,
                score=score,
            )
        )

    for concept in concepts:
        score = _score_match(terms, concept.title, concept.related_concepts)
        if score <= 0:
            # No textual match; the source-count bonus alone shouldn't
            # surface unrelated concepts.
            continue
        score += len(concept.sources) * _CONCEPT_SOURCE_BONUS
        snippet = await _read_first_paragraph(concept.path)
        hits.append(
            WikiHit(
                type="concept",
                path=str(concept.path.relative_to(vault_path)),
                title=concept.title,
                snippet=snippet or concept.title,
                score=score,
            )
        )

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:top_k]


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _score_match(terms: list[str], title: str, secondary: list[str]) -> float:
    title_lower = title.lower()
    secondary_lower = " ".join(secondary).lower() if secondary else ""
    score = 0.0
    for term in terms:
        if term in title_lower:
            score += _TITLE_WEIGHT
        if secondary_lower and term in secondary_lower:
            score += _TAG_WEIGHT
    return score


async def _read_first_paragraph(path: Path) -> str:
    """Return the first non-empty body paragraph of a markdown file."""
    async with aiofiles.open(path, encoding="utf-8") as fh:
        text = await fh.read()
    body = text
    if body.startswith("---\n"):
        end = body.find("\n---\n", 4)
        if end > 0:
            body = body[end + 5 :]
    for chunk in body.split("\n\n"):
        cleaned = chunk.strip()
        if cleaned:
            return cleaned[:_SNIPPET_MAX]
    return ""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@app.command(name="wiki-query")
def main(
    vault: Annotated[Path, typer.Argument(help="Path to the user's vault")],
    query: Annotated[str, typer.Argument(help="Search query (whitespace-separated terms)")],
    top_k: Annotated[int, typer.Option("--top-k", help="Maximum hits to return")] = 10,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG-level logging."),
    ] = False,
) -> None:
    """Run a wiki keyword search and emit JSON to stdout."""
    configure_runner_logging(verbose=verbose)
    try:
        hits = asyncio.run(query_wiki(vault, query, top_k=top_k))
    except PaperWikiError as exc:
        logger.error("wiki_query.failed", error=str(exc))
        raise typer.Exit(exc.exit_code) from exc

    typer.echo(json.dumps([asdict(h) for h in hits], indent=2))
    # Task 9.29 / D-9.29.1: substring search is the deterministic CLI default;
    # LLM-driven Q&A lives in the SKILL.  Emit the pointer to stderr so the
    # SKILL parsing of stdout stays JSON-clean while CLI users still see the
    # redirect tip in their terminal.
    typer.echo(
        "tip: for LLM-driven Q&A across the wiki, run /paper-wiki:wiki-query "
        "inside Claude Code (substring hits above are deterministic only).",
        err=True,
    )


if __name__ == "__main__":  # pragma: no cover - CLI entry
    app()


__all__ = ["WikiHit", "app", "query_wiki"]
