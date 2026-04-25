"""Dedup filter — drop papers already represented in the user's wiki.

This filter is the engine that prevents the digest from re-recommending
papers the user has already noted (in their vault) or already seen
(daily history). It is split into two pieces:

* :class:`DedupFilter` is pure stream logic. Given one or more
  :class:`KeyLoader`\\ s, it loads their dedup keys once at the start of
  the stream and then drops any paper whose normalized arxiv id or title
  key intersects the union.
* Built-in loader :class:`MarkdownVaultKeyLoader` reads markdown files
  (Obsidian-style or plain) with YAML frontmatter and extracts
  ``paper_id`` and ``title`` fields. Other layouts can plug in their own
  ``KeyLoader`` without forking core.

Identifier normalization goes through the helpers in
:mod:`paperwiki._internal.normalize`, which are the canonical source of
truth for arxiv id stripping and title key construction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import aiofiles
import yaml
from loguru import logger

from paperwiki._internal.normalize import normalize_arxiv_id, normalize_title_key

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable, Sequence

    from paperwiki.core.models import Paper, RunContext


_FRONTMATTER_PATTERN = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass(frozen=True)
class DedupKeys:
    """Frozen pair of normalized arxiv ids and title keys."""

    arxiv_ids: frozenset[str]
    title_keys: frozenset[str]

    @classmethod
    def empty(cls) -> DedupKeys:
        return cls(arxiv_ids=frozenset(), title_keys=frozenset())


@runtime_checkable
class KeyLoader(Protocol):
    """Loads dedup keys at the start of a pipeline run.

    Implementations may read the user's vault, daily-history files,
    a remote wiki backend, or any other source. They are called once
    per :meth:`DedupFilter.apply` invocation.
    """

    name: str

    async def load(self, ctx: RunContext) -> DedupKeys: ...


class DedupFilter:
    """Drop papers whose ids/titles intersect the union of loader keys."""

    name = "dedup"

    def __init__(self, loaders: Sequence[KeyLoader]) -> None:
        # An empty loader list is a deliberate no-op — useful for
        # composing recipes during development.
        self.loaders = list(loaders)

    async def apply(
        self,
        papers: AsyncIterator[Paper],
        ctx: RunContext,
    ) -> AsyncIterator[Paper]:
        arxiv_ids, title_keys = await self._load_keys(ctx)

        async for paper in papers:
            if self._is_duplicate(paper, arxiv_ids, title_keys):
                ctx.increment("filter.dedup.dropped")
                continue
            yield paper

    async def _load_keys(self, ctx: RunContext) -> tuple[set[str], set[str]]:
        all_arxiv_ids: set[str] = set()
        all_title_keys: set[str] = set()
        for loader in self.loaders:
            keys = await loader.load(ctx)
            all_arxiv_ids |= keys.arxiv_ids
            all_title_keys |= keys.title_keys
            ctx.increment(f"filter.dedup.loader.{loader.name}.arxiv_ids", by=len(keys.arxiv_ids))
            ctx.increment(f"filter.dedup.loader.{loader.name}.title_keys", by=len(keys.title_keys))
        return all_arxiv_ids, all_title_keys

    @staticmethod
    def _is_duplicate(
        paper: Paper,
        arxiv_ids: set[str],
        title_keys: set[str],
    ) -> bool:
        # Try the arxiv_id namespace first — it's the most reliable.
        if paper.canonical_id.startswith("arxiv:"):
            id_part = paper.canonical_id.split(":", 1)[1]
            normalized = normalize_arxiv_id(id_part)
            if normalized is not None and normalized in arxiv_ids:
                return True
        title_key = normalize_title_key(paper.title)
        return bool(title_key and title_key in title_keys)


class MarkdownVaultKeyLoader:
    """Load dedup keys from a directory tree of markdown files.

    Walks ``root`` recursively for ``*.md`` files, parses YAML
    frontmatter, and extracts ``paper_id`` and ``title`` (the field
    names are configurable). All extracted values flow through
    :func:`paperwiki._internal.normalize` so they collide cleanly with
    the canonical ids produced by source plugins.

    Missing or unreadable roots return an empty :class:`DedupKeys` and
    log a warning rather than raising — vault paths drift and the
    pipeline must remain useful.
    """

    def __init__(
        self,
        root: Path,
        *,
        arxiv_id_keys: Sequence[str] = ("canonical_id", "paper_id", "arxiv_id"),
        title_keys: Sequence[str] = ("title",),
        sources_list_keys: Sequence[str] = ("sources",),
    ) -> None:
        self.root = root
        self.arxiv_id_keys = tuple(arxiv_id_keys)
        self.title_keys = tuple(title_keys)
        self.sources_list_keys = tuple(sources_list_keys)
        self.name = f"markdown-vault:{root.name}"

    async def load(self, ctx: RunContext) -> DedupKeys:
        if not self.root.exists() or not self.root.is_dir():
            logger.warning("dedup.vault.missing", path=str(self.root))
            return DedupKeys.empty()

        arxiv_ids: set[str] = set()
        title_keys: set[str] = set()
        for path in self._iter_markdown_files(self.root):
            try:
                async with aiofiles.open(path, encoding="utf-8") as fh:
                    text = await fh.read()
            except OSError as exc:
                logger.warning("dedup.vault.read_error", path=str(path), error=str(exc))
                continue

            frontmatter = _parse_frontmatter(text)
            if frontmatter is None:
                continue

            # Single-id fields (legacy paper_id, modern canonical_id).
            for key in self.arxiv_id_keys:
                raw = frontmatter.get(key)
                if isinstance(raw, str):
                    normalized = normalize_arxiv_id(raw)
                    if normalized is not None:
                        arxiv_ids.add(normalized)
                        break

            # List-typed sources (concept frontmatter on the wiki).
            for key in self.sources_list_keys:
                raw_list = frontmatter.get(key)
                if isinstance(raw_list, list):
                    for item in raw_list:
                        if isinstance(item, str):
                            normalized = normalize_arxiv_id(item)
                            if normalized is not None:
                                arxiv_ids.add(normalized)
                    break

            for key in self.title_keys:
                raw = frontmatter.get(key)
                if isinstance(raw, str):
                    normalized = normalize_title_key(raw)
                    if normalized is not None:
                        title_keys.add(normalized)
                        break

        return DedupKeys(
            arxiv_ids=frozenset(arxiv_ids),
            title_keys=frozenset(title_keys),
        )

    @staticmethod
    def _iter_markdown_files(root: Path) -> Iterable[Path]:
        # Collect once so test-side ordering is deterministic.
        return sorted(root.rglob("*.md"))


def _parse_frontmatter(text: str) -> dict[str, object] | None:
    """Return the YAML frontmatter as a dict, or ``None`` if absent/invalid."""
    match = _FRONTMATTER_PATTERN.match(text)
    if match is None:
        return None
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    return data


__all__ = [
    "DedupFilter",
    "DedupKeys",
    "KeyLoader",
    "MarkdownVaultKeyLoader",
]
