"""``paperwiki.runners.wiki_query`` — keyword search across the wiki.

Invoked by the ``paperwiki:wiki-query`` SKILL via::

    ${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.wiki_query \
        <vault-path> <query>

Emits a JSON array of ``WikiHit`` records on stdout, ranked by a
**frequency * recency * tag-match** composite score (task 9.171):

* **Frequency** — how often query terms appear in the doc body. TF-style
  with sqrt damping so spammy notes don't dominate.
* **Recency** — newer notes rank higher via half-life decay against the
  file's mtime (default half-life 90 days).
* **Tag-match** — exact frontmatter-tag match boost on top of the body
  score; rewards curated metadata over incidental occurrences.

Weights are tunable via :class:`RankingWeights` (default tuned against
the project's own ``.omc/wiki/`` per task 9.171). Per SPEC §6, this
runner does not call any LLM — the SKILL synthesizes the answer
afterward, citing returned hits.

We deliberately use plain substring + token matching rather than vector
embeddings; at the ~100-source scale the wiki is built for, that is
enough and avoids embedding infrastructure (Karpathy's gist, see
``tasks/plan.md`` Appendix A). Detailed scoring formula lives in
``references/wiki-query-ranking.md``.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated

import aiofiles
import typer
from loguru import logger

from paperwiki._internal.logging import configure_runner_logging
from paperwiki.config.layout import WIKI_SUBDIR
from paperwiki.config.secrets import load_secrets_env
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


_CONCEPT_SOURCE_BONUS = 0.1
_SNIPPET_MAX = 200


@dataclass(frozen=True, slots=True)
class RankingWeights:
    """Weights for the v0.4.x wiki-query composite ranking (task 9.171).

    Defaults are tuned against the project's own ``.omc/wiki/`` so a
    representative search ("ralph boulder") still surfaces the
    canonical decision page. The full scoring formula is documented
    in ``references/wiki-query-ranking.md``.

    All weights are independent multipliers — set any to ``0.0`` to
    disable that signal entirely. Negative values are illegal but
    not validated here (the runner is the only writer).
    """

    # Term frequency in body — sqrt-damped so a 100-occurrence note
    # doesn't drown out a focused 1-occurrence one.
    frequency: float = 1.0

    # Recency boost. Half-life is :data:`recency_half_life_days`; a
    # doc modified that long ago gets exactly half the weight of a
    # just-modified doc. Set to 0 to ignore mtime entirely.
    recency: float = 0.5

    # Half-life in days for the recency exponential decay.
    recency_half_life_days: float = 90.0

    # Bonus added when a query term matches a frontmatter tag exactly.
    tag_match: float = 1.0

    # Title hits outweigh body hits — captures the existing v0.3.x
    # signal as a frequency multiplier on title-occurrence count.
    title_multiplier: float = 2.0


_DEFAULT_WEIGHTS = RankingWeights()


def _term_frequency(text: str, term: str) -> int:
    """Count case-insensitive occurrences of ``term`` in ``text``."""
    if not term:
        return 0
    return text.lower().count(term.lower())


def _recency_factor(
    *,
    body_path: Path,
    weights: RankingWeights,
    now: float | None = None,
) -> float:
    """Return a [0,1] multiplier favouring recently-modified files.

    Uses an exponential decay against ``body_path``'s mtime:
    ``2 ** (-age_days / half_life)``. Disabled when
    ``weights.recency == 0`` or ``half_life`` is non-positive.
    """
    if weights.recency <= 0 or weights.recency_half_life_days <= 0:
        return 1.0
    try:
        mtime = body_path.stat().st_mtime
    except OSError:
        return 1.0
    age_days = max(0.0, ((now or time.time()) - mtime) / 86400.0)
    return float(2 ** (-age_days / weights.recency_half_life_days))


def score_document(
    *,
    terms: list[str],
    title: str,
    tags: list[str],
    body_path: Path,
    weights: RankingWeights = _DEFAULT_WEIGHTS,
    now: float | None = None,
) -> float:
    """Compute the composite frequency * recency * tag-match score.

    Returns ``0.0`` when no query term has any positive signal so
    fully-unrelated documents stay out of the result list. The
    formula:

    .. code-block:: text

        body_freq  = Σ sqrt(count(term, body))
        title_hits = Σ count(term, title)
        tag_hits   = Σ I[term ∈ tags]

        recency = 2 ** (-age_days / half_life)        if weights.recency > 0 else 1

        raw     = weights.frequency * (body_freq + weights.title_multiplier * title_hits)
                + weights.tag_match * tag_hits
        boosted = raw * (1 + weights.recency * (recency - 1))

    The recency form ``(1 + w*(r-1))`` keeps a fresh doc at full
    weight (``r=1``) and an arbitrarily old one at ``1 - w`` of its
    raw score, so ``w=0`` cleanly disables the signal.
    """
    if not terms:
        return 0.0

    # Read body once for term-frequency.
    try:
        body = body_path.read_text(encoding="utf-8")
    except OSError:
        body = ""

    body_freq = 0.0
    title_hits = 0
    tag_hits = 0
    title_lower = title.lower()
    tag_set = {t.lower() for t in tags}
    for term in terms:
        # sqrt-damped TF — repeats compound but with diminishing returns.
        count = _term_frequency(body, term)
        if count > 0:
            body_freq += math.sqrt(count)
        if term in title_lower:
            title_hits += 1
        if term.lower() in tag_set:
            tag_hits += 1

    raw = weights.frequency * (body_freq + weights.title_multiplier * title_hits)
    raw += weights.tag_match * tag_hits

    if raw <= 0.0:
        return 0.0

    recency = _recency_factor(body_path=body_path, weights=weights, now=now)
    return raw * (1.0 + weights.recency * (recency - 1.0))


async def query_wiki(
    vault_path: Path,
    query: str,
    *,
    top_k: int = 10,
    wiki_subdir: str = WIKI_SUBDIR,
    weights: RankingWeights = _DEFAULT_WEIGHTS,
) -> list[WikiHit]:
    """Search the vault's wiki for ``query``; return up to ``top_k`` hits.

    Per task 9.171, ranking now runs the composite frequency * recency
    * tag-match score (see :func:`score_document`). The legacy pure-
    keyword fallback is gone — it's just the new score with all
    non-frequency weights at zero.
    """
    terms = [t for t in query.lower().split() if t]
    if not terms:
        return []

    backend = MarkdownWikiBackend(vault_path=vault_path, wiki_subdir=wiki_subdir)
    sources = await backend.list_sources()
    concepts = await backend.list_concepts()

    hits: list[WikiHit] = []

    for source in sources:
        score = score_document(
            terms=terms,
            title=source.title,
            tags=source.tags,
            body_path=source.path,
            weights=weights,
        )
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
        score = score_document(
            terms=terms,
            title=concept.title,
            tags=concept.related_concepts,
            body_path=concept.path,
            weights=weights,
        )
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


# Legacy alias preserved for direct test imports — equivalent to running
# score_document with all signals enabled. Kept until the v0.4.0
# release-gate confirms no out-of-tree caller depends on it.
def _score_match(terms: list[str], title: str, secondary: list[str]) -> float:
    """Legacy v0.3.x scorer kept for test backwards-compat.

    Prefer :func:`score_document` which includes recency + tag-match.
    """
    title_lower = title.lower()
    secondary_lower = " ".join(secondary).lower() if secondary else ""
    score = 0.0
    for term in terms:
        if term in title_lower:
            score += _DEFAULT_WEIGHTS.title_multiplier * _DEFAULT_WEIGHTS.frequency
        if secondary_lower and term in secondary_lower:
            score += _DEFAULT_WEIGHTS.tag_match
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
    weight_frequency: Annotated[
        float,
        typer.Option(
            "--weight-frequency",
            help="Composite-score weight on body term frequency (task 9.171).",
        ),
    ] = _DEFAULT_WEIGHTS.frequency,
    weight_recency: Annotated[
        float,
        typer.Option(
            "--weight-recency",
            help="Composite-score weight on file mtime recency (0 disables).",
        ),
    ] = _DEFAULT_WEIGHTS.recency,
    weight_tag_match: Annotated[
        float,
        typer.Option(
            "--weight-tag-match",
            help="Composite-score weight on exact frontmatter-tag match.",
        ),
    ] = _DEFAULT_WEIGHTS.tag_match,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG-level logging."),
    ] = False,
) -> None:
    """Run a wiki keyword search and emit JSON to stdout."""
    configure_runner_logging(verbose=verbose)
    # Task 9.180 / D-U: uniform secrets-load contract across runners.
    load_secrets_env()
    weights = RankingWeights(
        frequency=weight_frequency,
        recency=weight_recency,
        tag_match=weight_tag_match,
    )
    try:
        hits = asyncio.run(query_wiki(vault, query, top_k=top_k, weights=weights))
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


__all__ = [
    "RankingWeights",
    "WikiHit",
    "app",
    "query_wiki",
    "score_document",
]
