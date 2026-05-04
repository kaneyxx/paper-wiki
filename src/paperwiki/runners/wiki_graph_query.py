"""``paperwiki.runners.wiki_graph_query`` — query the wiki knowledge graph.

Phase 1 task 9.159 of the v0.4.x consensus plan. Backs the new
``paper-wiki:wiki-graph`` SKILL + ``/paper-wiki:wiki-graph`` slash
command.

The runner answers three structured queries against
``<vault>/Wiki/.graph/edges.jsonl``:

* ``--papers-citing <paper>`` — entities that wikilink to the target.
* ``--concepts-in-topic <topic>`` — concepts referenced by the topic.
* ``--collaborators-of <person>`` — people the target person links to.

Two output formats per **D-Q**: ``--json`` (default, machine-friendly,
emitted by the SKILL pipe to Claude) and ``--pretty`` (Markdown table,
human-readable from the CLI).

Per **R13** + Scenario 6, the query runner consults
:func:`paperwiki.runners.wiki_compile_graph.graph_is_stale` and
auto-rebuilds the cache before answering when the source Markdown is
newer than the cached ``edges.jsonl``. Manual ``--rebuild`` forces a
fresh build regardless. ``--json`` keeps the output compact so the
SKILL pipe to Claude stays under control; users get human-readable
output via ``--pretty``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any

import typer
from loguru import logger

from paperwiki._internal.logging import configure_runner_logging
from paperwiki.config.layout import WIKI_SUBDIR
from paperwiki.config.vault_resolver import resolve_vault
from paperwiki.core.errors import PaperWikiError, UserError
from paperwiki.runners.wiki_compile_graph import (
    EDGES_FILENAME,
    GRAPH_SUBDIR,
    compile_graph,
    graph_is_stale,
    iter_edges_jsonl,
    walk_entities,
)

app = typer.Typer(
    add_completion=False,
    help="Query the wiki knowledge graph.",
    no_args_is_help=True,
)


def _build_alias_to_id(vault_path: Path, wiki_subdir: str) -> dict[str, str]:
    """Build alias → entity_id resolution map from the typed-subdir notes.

    Mirrors the resolution logic in :mod:`wiki_compile_graph` so that
    user-supplied targets like ``p1`` or ``arxiv:2401.00001`` resolve to
    the same canonical ``papers/p1`` ids that the graph emits.
    """
    wiki_root = vault_path / wiki_subdir
    alias_to_id: dict[str, str] = {}
    for entity in walk_entities(wiki_root):
        for alias in entity.aliases:
            alias_to_id.setdefault(alias, entity.entity_id)
    return alias_to_id


def _resolve_target(
    vault_path: Path,
    wiki_subdir: str,
    target: str,
) -> str | None:
    """Resolve a user-supplied query target to its canonical entity_id.

    Returns ``None`` when the target is not recognised — the caller
    treats this as an empty result rather than an error.
    """
    alias_to_id = _build_alias_to_id(vault_path, wiki_subdir)
    return alias_to_id.get(target.strip())


def _ensure_fresh_graph(
    vault_path: Path,
    wiki_subdir: str,
    *,
    force_rebuild: bool,
) -> None:
    """Auto-rebuild the cache when stale, or unconditionally when forced."""
    if force_rebuild or graph_is_stale(vault_path, wiki_subdir=wiki_subdir):
        logger.info(
            "wiki_graph_query.rebuild.start",
            vault=str(vault_path),
            forced=force_rebuild,
        )
        asyncio.run(
            compile_graph(
                vault_path,
                wiki_subdir=wiki_subdir,
                force_rebuild=force_rebuild,
            )
        )


def query(
    vault_path: Path,
    *,
    wiki_subdir: str = WIKI_SUBDIR,
    papers_citing: str | None = None,
    concepts_in_topic: str | None = None,
    collaborators_of: str | None = None,
    force_rebuild: bool = False,
) -> list[dict[str, Any]]:
    """Run one of the three v0.4.x graph queries.

    Exactly one of ``papers_citing``, ``concepts_in_topic``, or
    ``collaborators_of`` must be set — the CLI enforces this. Returns
    a list of edge records (each a dict with at least ``src`` / ``dst``
    / ``type`` keys) so callers can pipe through ``json.dumps`` or
    :func:`format_pretty` without further processing.

    Per R13: auto-rebuilds the ``.graph/`` cache when stale.
    """
    queries = [papers_citing, concepts_in_topic, collaborators_of]
    if sum(q is not None for q in queries) != 1:
        msg = "exactly one of papers_citing / concepts_in_topic / collaborators_of must be set"
        raise PaperWikiError(msg)

    _ensure_fresh_graph(vault_path, wiki_subdir, force_rebuild=force_rebuild)

    edges_path = vault_path / wiki_subdir / GRAPH_SUBDIR / EDGES_FILENAME
    if not edges_path.exists():
        # Empty vault — graph cache wasn't even produced. Treat as
        # empty-result rather than crashing the SKILL pipe.
        return []

    if papers_citing is not None:
        target_id = _resolve_target(vault_path, wiki_subdir, papers_citing)
        if target_id is None:
            return []
        records = [
            {
                "src": edge.src,
                "dst": edge.dst,
                "type": edge.type.value if hasattr(edge.type, "value") else edge.type,
                "weight": edge.weight,
            }
            for edge in iter_edges_jsonl(edges_path)
            if edge.dst == target_id
        ]
        return records

    if concepts_in_topic is not None:
        topic_id = _resolve_target(vault_path, wiki_subdir, concepts_in_topic)
        if topic_id is None:
            return []
        records = [
            {
                "src": edge.src,
                "dst": edge.dst,
                "type": edge.type.value if hasattr(edge.type, "value") else edge.type,
                "weight": edge.weight,
            }
            for edge in iter_edges_jsonl(edges_path)
            if edge.src == topic_id and edge.dst.startswith("concepts/")
        ]
        return records

    # collaborators_of branch.
    person_id = _resolve_target(vault_path, wiki_subdir, collaborators_of or "")
    if person_id is None:
        return []
    records = [
        {
            "src": edge.src,
            "dst": edge.dst,
            "type": edge.type.value if hasattr(edge.type, "value") else edge.type,
            "weight": edge.weight,
        }
        for edge in iter_edges_jsonl(edges_path)
        if edge.src == person_id and edge.dst.startswith("people/")
    ]
    return records


def format_pretty(records: list[dict[str, Any]], *, header: str) -> str:
    """Render query records as a Markdown table for human consumption."""
    if not records:
        return f"# {header}\n\nNo edges matched.\n"
    lines = [
        f"# {header}",
        "",
        "| src | dst | type | weight |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(f"| {r['src']} | {r['dst']} | {r['type']} | {r['weight']} |" for r in records)
    lines.append("")
    return "\n".join(lines)


@app.command()
def main(
    vault: Annotated[
        Path | None,
        typer.Argument(
            help=(
                "Path to the Obsidian vault root. Optional (Task 9.194 / D-V) — "
                "falls back to $PAPERWIKI_DEFAULT_VAULT, then "
                "~/.config/paper-wiki/config.toml::default_vault."
            ),
            show_default=False,
        ),
    ] = None,
    wiki_subdir: Annotated[
        str,
        typer.Option("--wiki-subdir", help="Wiki subdir under the vault."),
    ] = WIKI_SUBDIR,
    papers_citing: Annotated[
        str | None,
        typer.Option(
            "--papers-citing",
            help="Slug or canonical_id of the paper to find citations to.",
        ),
    ] = None,
    concepts_in_topic: Annotated[
        str | None,
        typer.Option(
            "--concepts-in-topic",
            help="Slug of the topic whose concepts to enumerate.",
        ),
    ] = None,
    collaborators_of: Annotated[
        str | None,
        typer.Option(
            "--collaborators-of",
            help="Slug of the person whose linked collaborators to list.",
        ),
    ] = None,
    rebuild: Annotated[
        bool,
        typer.Option("--rebuild", help="Force rebuild the graph cache before query."),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit JSON (default for SKILL pipe).",
        ),
    ] = True,
    pretty: Annotated[
        bool,
        typer.Option(
            "--pretty",
            help="Emit a Markdown table for human consumption.",
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG-level logging."),
    ] = False,
) -> None:
    """Query the wiki knowledge graph and emit JSON or Markdown."""
    configure_runner_logging(verbose=verbose)
    if papers_citing is None and concepts_in_topic is None and collaborators_of is None:
        typer.echo(
            "error: exactly one of --papers-citing / --concepts-in-topic / "
            "--collaborators-of must be set",
            err=True,
        )
        raise typer.Exit(2)

    # Task 9.194 / D-V: resolve the vault when the positional was omitted.
    if vault is None:
        try:
            vault = resolve_vault(None)
        except UserError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(exc.exit_code) from exc
    else:
        vault = vault.expanduser()

    if not vault.is_dir():
        typer.echo(
            f"Error: vault path does not exist or is not a directory: {vault}",
            err=True,
        )
        raise typer.Exit(1)

    try:
        records = query(
            vault,
            wiki_subdir=wiki_subdir,
            papers_citing=papers_citing,
            concepts_in_topic=concepts_in_topic,
            collaborators_of=collaborators_of,
            force_rebuild=rebuild,
        )
    except PaperWikiError as exc:
        logger.error("wiki_graph_query.failed", error=str(exc))
        raise typer.Exit(exc.exit_code) from exc

    if pretty:
        if papers_citing:
            header = f"papers citing {papers_citing}"
        elif concepts_in_topic:
            header = f"concepts in topic {concepts_in_topic}"
        else:
            header = f"collaborators of {collaborators_of}"
        typer.echo(format_pretty(records, header=header))
        return

    # JSON path (default).
    if json_out:
        typer.echo(json.dumps(records, indent=2))


if __name__ == "__main__":  # pragma: no cover - CLI entry
    app()


__all__ = [
    "app",
    "format_pretty",
    "query",
]
