"""``paperwiki.runners.wiki_compile_graph`` — materialise the wiki graph.

Phase 1 task 9.157 of the v0.4.x consensus plan.

Walks ``<vault>/Wiki/{papers,concepts,topics,people}/`` and writes two
sidecar JSONL files into ``<vault>/Wiki/.graph/`` from the wikilinks +
frontmatter ``references:`` lists found in each note. Frontmatter is
the canonical source of truth (D-B); these JSONL files are a derived
*query cache* rebuilt on demand — deleting them loses no information,
only query speed.

The runner is **idempotent**: same vault state ⇒ byte-identical output.
This is enforced via deterministic sort keys at write time and a
no-touch contract for non-dotfile inputs.

Forward-compat per consensus plan iter-2 R12 + Scenario 7: on read of
an existing ``edges.jsonl`` with unknown ``EdgeType`` values (emitted
by a future paperwiki version), the value is preserved verbatim with a
``loguru.warning``. On write, only canonical :class:`EdgeType` enum
members are emitted by Python.

Auto-rebuild per R13 + Scenario 6: ``graph_is_stale`` reports True when
the sidecar is missing OR older than the newest ``*.md`` mtime under
``<vault>/Wiki/``. Callers (notably ``wiki_graph_query``, task 9.159)
should consult this before reading the cache.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import aiofiles
import typer
import yaml
from loguru import logger

from paperwiki._internal.logging import configure_runner_logging
from paperwiki.config.layout import WIKI_SUBDIR
from paperwiki.core.errors import PaperWikiError
from paperwiki.core.models import EdgeType

# Typed-subdir layout per D-I. The runner only walks these four
# directories — anything else under ``Wiki/`` (notably the sidecar
# ``.graph/`` directory itself) is skipped to avoid cycles.
TYPED_SUBDIRS: tuple[str, ...] = ("papers", "concepts", "topics", "people")
GRAPH_SUBDIR = ".graph"
EDGES_FILENAME = "edges.jsonl"
CITATIONS_FILENAME = "citations.jsonl"

# ``[[target]]`` or ``[[target|display]]`` — captures only the target.
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

app = typer.Typer(
    add_completion=False,
    help="Materialise <vault>/Wiki/.graph/{edges,citations}.jsonl.",
    no_args_is_help=True,
)


@dataclass(frozen=True, slots=True)
class EdgeRecord:
    """One row of ``edges.jsonl``. ``type`` is ``EdgeType | str`` to keep
    the read side tolerant of unknown values emitted by future versions.
    """

    src: str
    dst: str
    type: EdgeType | str
    weight: float = 1.0
    evidence: str | None = None
    subtype: str | None = None

    def to_jsonable(self) -> dict[str, Any]:
        """Render to a dict whose JSON form is byte-stable across runs."""
        # ``EdgeType`` is a ``StrEnum`` so ``str(...)`` returns the value.
        type_str = self.type.value if isinstance(self.type, EdgeType) else self.type
        return {
            "src": self.src,
            "dst": self.dst,
            "type": type_str,
            "weight": self.weight,
            "evidence": self.evidence,
            "subtype": self.subtype,
        }


@dataclass(frozen=True, slots=True)
class CitationRecord:
    """One row of ``citations.jsonl``. Paper-paper references only."""

    paper: str
    references: tuple[str, ...]

    def to_jsonable(self) -> dict[str, Any]:
        return {"paper": self.paper, "references": list(self.references)}


@dataclass(frozen=True, slots=True)
class CompileGraphResult:
    """Summary returned by :func:`compile_graph`."""

    entity_count: int
    edge_count: int
    citation_count: int
    edges_path: Path
    citations_path: Path


@dataclass(frozen=True, slots=True)
class ParsedEntity:
    """Public read-only view of one parsed wiki note.

    Exposed so the wiki-lint runner (task 9.158) can reuse the
    typed-subdir walker without duplicating the parser.
    """

    entity_id: str
    entity_type: str
    aliases: frozenset[str]
    body_wikilinks: tuple[str, ...]
    frontmatter: dict[str, Any]


def graph_is_stale(vault_path: Path, *, wiki_subdir: str = WIKI_SUBDIR) -> bool:
    """Return True if the graph cache is missing or older than its source.

    Compares the mtime of ``<vault>/<wiki_subdir>/.graph/edges.jsonl`` to
    the newest ``*.md`` mtime under ``<vault>/<wiki_subdir>/``. Used by
    ``wiki_graph_query`` (task 9.159) to decide whether to auto-rebuild
    before answering a query.
    """
    wiki_root = vault_path / wiki_subdir
    edges_path = wiki_root / GRAPH_SUBDIR / EDGES_FILENAME
    if not edges_path.exists():
        return True
    edges_mtime = edges_path.stat().st_mtime
    newest_md_mtime = 0.0
    for subdir in TYPED_SUBDIRS:
        sub = wiki_root / subdir
        if not sub.is_dir():
            continue
        for md in sub.glob("*.md"):
            if md.name.startswith("."):
                continue
            newest_md_mtime = max(newest_md_mtime, md.stat().st_mtime)
    return newest_md_mtime > edges_mtime


def iter_edges_jsonl(path: Path) -> Iterator[EdgeRecord]:
    """Yield :class:`EdgeRecord` rows from an existing edges.jsonl.

    Unknown ``type`` values are preserved verbatim with one
    ``loguru.warning`` per unknown value (per consensus plan iter-2
    R12 / Scenario 7). Idempotent re-emit writes them back unchanged.
    """
    seen_unknown: set[str] = set()
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        type_raw = record.get("type", "")
        try:
            type_value: EdgeType | str = EdgeType(type_raw)
        except ValueError:
            # Forward-compat: preserve unknown values verbatim, warn once.
            if type_raw not in seen_unknown:
                logger.warning(
                    "wiki_compile_graph.edge_type.unknown",
                    value=type_raw,
                    note="preserved verbatim; expected canonical EdgeType",
                )
                seen_unknown.add(type_raw)
            type_value = type_raw
        yield EdgeRecord(
            src=record["src"],
            dst=record["dst"],
            type=type_value,
            weight=float(record.get("weight", 1.0)),
            evidence=record.get("evidence"),
            subtype=record.get("subtype"),
        )


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a Markdown body into ``(frontmatter_dict, body_text)``."""
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return {}, text
    raw = match.group(1)
    try:
        loaded = yaml.safe_load(raw)
    except yaml.YAMLError:
        # Malformed frontmatter — treat as missing rather than crash the
        # whole compile pass. The wiki-lint runner (9.158) catches this.
        return {}, text[match.end() :]
    if not isinstance(loaded, dict):
        return {}, text[match.end() :]
    return loaded, text[match.end() :]


def _entity_id_from_path(file_path: Path, wiki_root: Path) -> str:
    """``papers/arxiv-2401-00001.md`` → ``papers/arxiv-2401-00001``."""
    rel = file_path.relative_to(wiki_root)
    return rel.with_suffix("").as_posix()


def _aliases_for_entity(
    entity_id: str,
    frontmatter: dict[str, Any],
) -> frozenset[str]:
    """Return every string that resolves to ``entity_id`` via wikilink.

    Aliases include:

    * The bare slug (path tail).
    * The full ``<subdir>/<slug>`` form.
    * ``frontmatter["canonical_id"]`` if present.
    * Any string in ``frontmatter["aliases"]``.
    * Filename-style transforms of ``canonical_id`` (e.g.
      ``arxiv:2401.00001`` ⇆ ``arxiv-2401-00001``).
    """
    slug = entity_id.split("/", 1)[1]
    aliases: set[str] = {slug, entity_id}
    canonical = frontmatter.get("canonical_id")
    if isinstance(canonical, str) and canonical.strip():
        aliases.add(canonical.strip())
        # Filename-safe transform: replace ``:`` and ``.`` with ``-``.
        aliases.add(canonical.strip().replace(":", "-").replace(".", "-"))
    fm_aliases = frontmatter.get("aliases")
    if isinstance(fm_aliases, list):
        for a in fm_aliases:
            if isinstance(a, str) and a.strip():
                aliases.add(a.strip())
    return frozenset(aliases)


def _parse_entity_file(file_path: Path, wiki_root: Path) -> ParsedEntity | None:
    """Parse one ``.md`` file. Returns ``None`` for non-typed files."""
    rel = file_path.relative_to(wiki_root)
    if not rel.parts:
        return None
    entity_type = rel.parts[0]
    if entity_type not in TYPED_SUBDIRS:
        return None
    text = file_path.read_text(encoding="utf-8")
    frontmatter, body = _parse_frontmatter(text)
    entity_id = _entity_id_from_path(file_path, wiki_root)
    aliases = _aliases_for_entity(entity_id, frontmatter)
    body_wikilinks = tuple(_WIKILINK_RE.findall(body))
    return ParsedEntity(
        entity_id=entity_id,
        entity_type=entity_type,
        aliases=aliases,
        body_wikilinks=body_wikilinks,
        frontmatter=frontmatter,
    )


def _walk_typed_subdirs(wiki_root: Path) -> Iterator[Path]:
    """Yield non-dotfile ``.md`` paths under each typed subdir."""
    for subdir in TYPED_SUBDIRS:
        sub = wiki_root / subdir
        if not sub.is_dir():
            continue
        for md in sorted(sub.glob("*.md")):
            if md.name.startswith("."):
                continue
            yield md


def walk_entities(wiki_root: Path) -> list[ParsedEntity]:
    """Public typed-subdir walker (used by wiki-lint task 9.158).

    Returns parsed entities from all four typed subdirs in entity-id
    sorted order. Skips dotfiles and non-typed subdirs (e.g. ``.graph``).
    """
    return sorted(
        (
            entity
            for path in _walk_typed_subdirs(wiki_root)
            if (entity := _parse_entity_file(path, wiki_root)) is not None
        ),
        key=lambda e: e.entity_id,
    )


def _build_alias_map(
    entities: list[ParsedEntity],
) -> dict[str, str]:
    """Flatten entity aliases into ``alias -> entity_id``.

    Last-writer wins for collision; the runner is deterministic because
    entities are processed in sorted order.
    """
    alias_map: dict[str, str] = {}
    for entity in entities:
        for alias in entity.aliases:
            alias_map.setdefault(alias, entity.entity_id)
    return alias_map


def _infer_edge_type(src_kind: str, dst_kind: str) -> EdgeType:
    """v0.4.0 default-edge-type heuristic.

    * paper → paper: CITES
    * everything else: BUILDS_ON

    Users can hand-edit ``edges.jsonl`` for richer types post-compile.
    Future versions may parse section headings to auto-tag richer
    relations.
    """
    if src_kind == "papers" and dst_kind == "papers":
        return EdgeType.CITES
    return EdgeType.BUILDS_ON


def _build_records(
    entities: list[ParsedEntity],
    alias_map: dict[str, str],
) -> tuple[list[EdgeRecord], list[CitationRecord]]:
    edges: list[EdgeRecord] = []
    citations: list[CitationRecord] = []
    entity_kind_by_id = {e.entity_id: e.entity_type for e in entities}
    for entity in entities:
        cited_papers: list[str] = []
        for raw_target in entity.body_wikilinks:
            target = raw_target.strip()
            resolved = alias_map.get(target)
            if resolved is None or resolved == entity.entity_id:
                # Unresolved target → wiki-lint (9.158) flags as
                # BROKEN_LINK; skip from the graph.
                continue
            dst_kind = entity_kind_by_id.get(resolved, "")
            edge_type = _infer_edge_type(entity.entity_type, dst_kind)
            edges.append(
                EdgeRecord(
                    src=entity.entity_id,
                    dst=resolved,
                    type=edge_type,
                )
            )
            if entity.entity_type == "papers" and dst_kind == "papers":
                cited_papers.append(resolved)
        if entity.entity_type == "papers" and cited_papers:
            citations.append(
                CitationRecord(
                    paper=entity.entity_id,
                    references=tuple(sorted(set(cited_papers))),
                )
            )
    return edges, citations


def _sort_edges(edges: list[EdgeRecord]) -> list[EdgeRecord]:
    """Deterministic sort key: ``(src, dst, type, subtype, evidence)``."""

    def _key(e: EdgeRecord) -> tuple[str, str, str, str, str]:
        type_str = e.type.value if isinstance(e.type, EdgeType) else e.type
        return (e.src, e.dst, type_str, e.subtype or "", e.evidence or "")

    return sorted(edges, key=_key)


def _sort_citations(records: list[CitationRecord]) -> list[CitationRecord]:
    return sorted(records, key=lambda r: r.paper)


async def _write_jsonl_atomic(path: Path, records: list[dict[str, Any]]) -> None:
    """Write JSONL with deterministic key ordering, atomic same-fs."""
    body = "".join(
        json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n" for record in records
    )
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    async with aiofiles.open(tmp_path, "w", encoding="utf-8") as fh:
        await fh.write(body)
    tmp_path.replace(path)


async def compile_graph(
    vault_path: Path,
    *,
    wiki_subdir: str = WIKI_SUBDIR,
    force_rebuild: bool = False,
) -> CompileGraphResult:
    """Walk the wiki, build edges + citations, write the sidecar JSONL.

    Args:
        vault_path: Path to the user's Obsidian vault root.
        wiki_subdir: Subdir under ``vault_path`` holding the wiki notes.
            Defaults to :data:`paperwiki.config.layout.WIKI_SUBDIR`.
        force_rebuild: When True, rebuild even if ``graph_is_stale``
            reports the cache is fresh. Used by ``--rebuild`` CLI flag.

    Returns:
        :class:`CompileGraphResult` with counts + sidecar paths.

    Raises:
        :class:`PaperWikiError`: if ``vault_path`` is missing or the
            ``Wiki/`` subdir does not exist.
    """
    wiki_root = vault_path / wiki_subdir
    if not wiki_root.is_dir():
        msg = f"wiki root missing: {wiki_root}"
        raise PaperWikiError(msg)
    graph_dir = wiki_root / GRAPH_SUBDIR
    edges_path = graph_dir / EDGES_FILENAME
    citations_path = graph_dir / CITATIONS_FILENAME

    if not force_rebuild and not graph_is_stale(vault_path, wiki_subdir=wiki_subdir):
        # Cache is fresh — return summary without touching disk.
        logger.info(
            "wiki_compile_graph.skip_fresh_cache",
            edges_path=str(edges_path),
        )
        return CompileGraphResult(
            entity_count=sum(1 for _ in _walk_typed_subdirs(wiki_root)),
            edge_count=sum(1 for line in edges_path.read_text().splitlines() if line.strip()),
            citation_count=sum(
                1 for line in citations_path.read_text().splitlines() if line.strip()
            )
            if citations_path.exists()
            else 0,
            edges_path=edges_path,
            citations_path=citations_path,
        )

    graph_dir.mkdir(parents=True, exist_ok=True)

    logger.info("wiki_compile_graph.walk.start", wiki_root=str(wiki_root))
    entities = sorted(
        (
            entity
            for path in _walk_typed_subdirs(wiki_root)
            if (entity := _parse_entity_file(path, wiki_root)) is not None
        ),
        key=lambda e: e.entity_id,
    )
    logger.info(
        "wiki_compile_graph.walk.complete",
        entity_count=len(entities),
    )

    alias_map = _build_alias_map(entities)
    edges, citations = _build_records(entities, alias_map)
    edges = _sort_edges(edges)
    citations = _sort_citations(citations)

    logger.info(
        "wiki_compile_graph.write.start",
        edge_count=len(edges),
        citation_count=len(citations),
    )
    await _write_jsonl_atomic(edges_path, [e.to_jsonable() for e in edges])
    await _write_jsonl_atomic(citations_path, [c.to_jsonable() for c in citations])
    logger.info(
        "wiki_compile_graph.write.complete",
        edges_path=str(edges_path),
        citations_path=str(citations_path),
    )

    return CompileGraphResult(
        entity_count=len(entities),
        edge_count=len(edges),
        citation_count=len(citations),
        edges_path=edges_path,
        citations_path=citations_path,
    )


@app.command()
def main(
    vault: Annotated[
        Path,
        typer.Argument(
            help="Path to the Obsidian vault root.",
            exists=True,
            file_okay=False,
            dir_okay=True,
        ),
    ],
    wiki_subdir: Annotated[
        str,
        typer.Option("--wiki-subdir", help="Wiki subdir under the vault."),
    ] = WIKI_SUBDIR,
    rebuild: Annotated[
        bool,
        typer.Option(
            "--rebuild",
            help="Force rebuild even when the cache is fresh.",
        ),
    ] = False,
) -> None:
    """Materialise ``<vault>/Wiki/.graph/{edges,citations}.jsonl``."""
    configure_runner_logging()
    result = asyncio.run(compile_graph(vault, wiki_subdir=wiki_subdir, force_rebuild=rebuild))
    typer.echo(
        json.dumps(
            {
                "entity_count": result.entity_count,
                "edge_count": result.edge_count,
                "citation_count": result.citation_count,
                "edges_path": str(result.edges_path),
                "citations_path": str(result.citations_path),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    app()


__all__ = [
    "CITATIONS_FILENAME",
    "EDGES_FILENAME",
    "GRAPH_SUBDIR",
    "TYPED_SUBDIRS",
    "CitationRecord",
    "CompileGraphResult",
    "EdgeRecord",
    "ParsedEntity",
    "compile_graph",
    "graph_is_stale",
    "iter_edges_jsonl",
    "walk_entities",
]
