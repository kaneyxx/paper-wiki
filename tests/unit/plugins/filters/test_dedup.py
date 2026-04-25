"""Unit tests for paperwiki.plugins.filters.dedup.

Two layers:

* :class:`DedupFilter` is pure logic — drops papers whose normalized
  arxiv id or title key intersects keys provided by one or more
  :class:`KeyLoader`\\ s.
* :class:`MarkdownVaultKeyLoader` reads markdown files with YAML
  frontmatter and produces those keys.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

from paperwiki.core.models import Author, Paper, RunContext
from paperwiki.plugins.filters.dedup import (
    DedupFilter,
    DedupKeys,
    MarkdownVaultKeyLoader,
)


def _make_paper(canonical_id: str, title: str = "Stub Title") -> Paper:
    return Paper(
        canonical_id=canonical_id,
        title=title,
        authors=[Author(name="A. Author")],
        abstract="Stub abstract content.",
        published_at=datetime(2026, 4, 20, tzinfo=UTC),
    )


def _make_ctx() -> RunContext:
    return RunContext(target_date=datetime(2026, 4, 25, tzinfo=UTC), config_snapshot={})


async def _stream(papers: list[Paper]) -> AsyncIterator[Paper]:
    for paper in papers:
        yield paper


# ---------------------------------------------------------------------------
# DedupFilter (pure logic)
# ---------------------------------------------------------------------------


class _StaticLoader:
    def __init__(self, name: str, keys: DedupKeys) -> None:
        self.name = name
        self._keys = keys

    async def load(self, ctx: RunContext) -> DedupKeys:
        return self._keys


class TestDedupFilterPureLogic:
    async def test_no_loaders_passes_everything(self) -> None:
        flt = DedupFilter(loaders=[])
        papers = [_make_paper("arxiv:1"), _make_paper("arxiv:2")]
        kept = [p async for p in flt.apply(_stream(papers), _make_ctx())]
        assert kept == papers

    async def test_drops_by_arxiv_id_match(self) -> None:
        loader = _StaticLoader(
            "vault",
            DedupKeys(arxiv_ids=frozenset({"2506.13063"}), title_keys=frozenset()),
        )
        flt = DedupFilter(loaders=[loader])
        papers = [
            _make_paper("arxiv:2506.13063", title="Already Have"),
            _make_paper("arxiv:0001.0001", title="Brand New"),
        ]

        ctx = _make_ctx()
        kept = [p async for p in flt.apply(_stream(papers), ctx)]

        assert {p.canonical_id for p in kept} == {"arxiv:0001.0001"}
        assert ctx.counters["filter.dedup.dropped"] == 1

    async def test_drops_by_title_key_match(self) -> None:
        loader = _StaticLoader(
            "vault",
            DedupKeys(
                arxiv_ids=frozenset(),
                title_keys=frozenset({"prism2unlockingmultimodalai"}),
            ),
        )
        flt = DedupFilter(loaders=[loader])
        papers = [
            _make_paper(
                "s2:foo",
                title="PRISM2: Unlocking Multi-Modal AI",
            ),
            _make_paper("arxiv:0001.0001", title="A Different Paper"),
        ]

        ctx = _make_ctx()
        kept = [p async for p in flt.apply(_stream(papers), ctx)]

        assert {p.canonical_id for p in kept} == {"arxiv:0001.0001"}

    async def test_arxiv_id_normalized_before_match(self) -> None:
        # Loader carries normalized id; paper carries it via canonical_id which
        # also goes through normalization.
        loader = _StaticLoader(
            "vault",
            DedupKeys(arxiv_ids=frozenset({"2506.13063"}), title_keys=frozenset()),
        )
        flt = DedupFilter(loaders=[loader])
        # canonical_id with version suffix should still hit the key.
        papers = [_make_paper("arxiv:2506.13063v2", title="With Version")]

        ctx = _make_ctx()
        kept = [p async for p in flt.apply(_stream(papers), ctx)]

        assert kept == []
        assert ctx.counters["filter.dedup.dropped"] == 1

    async def test_multiple_loaders_union(self) -> None:
        loader_a = _StaticLoader(
            "vault",
            DedupKeys(arxiv_ids=frozenset({"1111.1111"}), title_keys=frozenset()),
        )
        loader_b = _StaticLoader(
            "history",
            DedupKeys(arxiv_ids=frozenset({"2222.2222"}), title_keys=frozenset()),
        )
        flt = DedupFilter(loaders=[loader_a, loader_b])
        papers = [
            _make_paper("arxiv:1111.1111"),
            _make_paper("arxiv:2222.2222"),
            _make_paper("arxiv:9999.9999"),
        ]

        ctx = _make_ctx()
        kept = [p async for p in flt.apply(_stream(papers), ctx)]

        assert {p.canonical_id for p in kept} == {"arxiv:9999.9999"}

    async def test_non_arxiv_canonical_id_falls_through_to_title_key(self) -> None:
        loader = _StaticLoader(
            "vault",
            DedupKeys(
                arxiv_ids=frozenset({"2506.13063"}),
                title_keys=frozenset({"validentry"}),
            ),
        )
        flt = DedupFilter(loaders=[loader])
        # Non-arxiv canonical_id can't match arxiv_ids, but title key still hits.
        papers = [_make_paper("s2:abc", title="Valid Entry")]

        ctx = _make_ctx()
        kept = [p async for p in flt.apply(_stream(papers), ctx)]

        assert kept == []

    async def test_filter_satisfies_protocol(self) -> None:
        from paperwiki.core.protocols import Filter

        assert isinstance(DedupFilter(loaders=[]), Filter)


# ---------------------------------------------------------------------------
# MarkdownVaultKeyLoader
# ---------------------------------------------------------------------------


def _write_note(
    root: Path,
    relative: str,
    *,
    paper_id: str | None = None,
    title: str | None = None,
    extra: str = "",
) -> None:
    """Helper: write a markdown file with the given frontmatter fields."""
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)

    lines = ["---"]
    if paper_id is not None:
        lines.append(f'paper_id: "{paper_id}"')
    if title is not None:
        lines.append(f'title: "{title}"')
    if extra:
        lines.append(extra)
    lines.append("---")
    lines.append("Body content.")
    target.write_text("\n".join(lines), encoding="utf-8")


class TestMarkdownVaultKeyLoader:
    async def test_loads_arxiv_id_and_title_key(self, tmp_path: Path) -> None:
        _write_note(
            tmp_path,
            "20_Research/Papers/foo.md",
            paper_id="arXiv:2506.13063",
            title="PRISM2: Unlocking Multi-Modal AI",
        )

        loader = MarkdownVaultKeyLoader(root=tmp_path)
        keys = await loader.load(_make_ctx())

        assert "2506.13063" in keys.arxiv_ids
        assert "prism2unlockingmultimodalai" in keys.title_keys

    async def test_handles_multiple_files(self, tmp_path: Path) -> None:
        _write_note(tmp_path, "a/foo.md", paper_id="2506.13063", title="Foo")
        _write_note(tmp_path, "b/bar.md", paper_id="2506.99999v2", title="Bar Quux")

        loader = MarkdownVaultKeyLoader(root=tmp_path)
        keys = await loader.load(_make_ctx())

        assert keys.arxiv_ids == frozenset({"2506.13063", "2506.99999"})
        assert "foo" in keys.title_keys
        assert "barquux" in keys.title_keys

    async def test_missing_root_returns_empty(self, tmp_path: Path) -> None:
        # Pointing at a non-existent path should not raise.
        loader = MarkdownVaultKeyLoader(root=tmp_path / "does-not-exist")
        keys = await loader.load(_make_ctx())
        assert keys.arxiv_ids == frozenset()
        assert keys.title_keys == frozenset()

    async def test_empty_root_returns_empty(self, tmp_path: Path) -> None:
        loader = MarkdownVaultKeyLoader(root=tmp_path)
        keys = await loader.load(_make_ctx())
        assert keys.arxiv_ids == frozenset()
        assert keys.title_keys == frozenset()

    async def test_skips_files_without_frontmatter(self, tmp_path: Path) -> None:
        (tmp_path / "no-frontmatter.md").write_text("Just body, no frontmatter.\n")
        _write_note(tmp_path, "good.md", paper_id="2506.13063", title="Good")

        loader = MarkdownVaultKeyLoader(root=tmp_path)
        keys = await loader.load(_make_ctx())

        assert keys.arxiv_ids == frozenset({"2506.13063"})

    async def test_skips_invalid_yaml(self, tmp_path: Path) -> None:
        (tmp_path / "broken.md").write_text("---\n: : invalid yaml :\n---\nbody\n")
        _write_note(tmp_path, "good.md", paper_id="2506.13063", title="Good")

        loader = MarkdownVaultKeyLoader(root=tmp_path)
        keys = await loader.load(_make_ctx())

        # Broken file is silently skipped; good file still loads.
        assert keys.arxiv_ids == frozenset({"2506.13063"})

    async def test_alternate_field_names(self, tmp_path: Path) -> None:
        # Some users use `arxiv_id` instead of `paper_id`.
        _write_note(tmp_path, "alt.md", extra='arxiv_id: "1234.5678"\ntitle: "Alt"')

        loader = MarkdownVaultKeyLoader(
            root=tmp_path,
            arxiv_id_keys=("paper_id", "arxiv_id"),
        )
        keys = await loader.load(_make_ctx())

        assert "1234.5678" in keys.arxiv_ids

    async def test_only_partial_frontmatter(self, tmp_path: Path) -> None:
        # Frontmatter with title only (no paper_id) still contributes a title_key.
        _write_note(tmp_path, "title-only.md", title="Just A Title")

        loader = MarkdownVaultKeyLoader(root=tmp_path)
        keys = await loader.load(_make_ctx())

        assert keys.arxiv_ids == frozenset()
        assert "justatitle" in keys.title_keys

    async def test_canonical_id_field_recognized(self, tmp_path: Path) -> None:
        """Wiki source files use ``canonical_id``; the loader picks it up."""
        _write_note(
            tmp_path,
            "Wiki/sources/arxiv_2506.13063.md",
            extra='canonical_id: "arxiv:2506.13063"\ntitle: "PRISM2"',
        )
        loader = MarkdownVaultKeyLoader(root=tmp_path)
        keys = await loader.load(_make_ctx())
        assert "2506.13063" in keys.arxiv_ids

    async def test_concept_sources_list_contributes_each_id(self, tmp_path: Path) -> None:
        """Wiki concept files list multiple sources; every entry contributes."""
        target = tmp_path / "Wiki/concepts/Vision-Language.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "---\n"
            'title: "Vision-Language"\n'
            'sources: ["arxiv:2506.13063", "arxiv:0001.0001"]\n'
            "---\n"
            "Body.\n",
            encoding="utf-8",
        )
        loader = MarkdownVaultKeyLoader(root=tmp_path)
        keys = await loader.load(_make_ctx())
        assert "2506.13063" in keys.arxiv_ids
        assert "0001.0001" in keys.arxiv_ids
