"""Unit tests for paperwiki.plugins.sources.paperclip.

The plugin shells out to the ``paperclip`` CLI and never makes network
calls itself. All tests stub ``asyncio.create_subprocess_exec`` so the
suite is hermetic and deterministic on machines without paperclip
installed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from paperwiki.core.errors import IntegrationError
from paperwiki.core.models import RunContext

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


# ---------------------------------------------------------------------------
# Test stubs
# ---------------------------------------------------------------------------


class _FakeProcess:
    """Stand-in for ``asyncio.subprocess.Process`` returned by ``create_subprocess_exec``."""

    def __init__(self, *, returncode: int, stdout: bytes, stderr: bytes) -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


def _patch_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    *,
    returncode: int = 0,
    stdout: bytes = b"[]",
    stderr: bytes = b"",
    raises: type[BaseException] | None = None,
    capture_argv: list[Sequence[str]] | None = None,
) -> None:
    """Patch ``asyncio.create_subprocess_exec`` for the paperclip module."""
    from paperwiki.plugins.sources import paperclip as paperclip_module

    async def fake_exec(*argv: str, **kwargs: object) -> _FakeProcess:
        if capture_argv is not None:
            capture_argv.append(argv)
        if raises is not None:
            raise raises("simulated failure")
        return _FakeProcess(returncode=returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(paperclip_module.asyncio, "create_subprocess_exec", fake_exec)


def _make_ctx() -> RunContext:
    return RunContext(target_date=datetime(2026, 4, 25, tzinfo=UTC), config_snapshot={})


def _hits_to_stdout(hits: Iterable[dict[str, object]]) -> bytes:
    return json.dumps(list(hits)).encode("utf-8")


async def _drain(source: object, ctx: RunContext) -> list[object]:
    return [paper async for paper in source.fetch(ctx)]  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Construction / protocol conformance
# ---------------------------------------------------------------------------


class TestConstructionAndProtocol:
    def test_satisfies_source_protocol(self) -> None:
        from paperwiki.core.protocols import Source
        from paperwiki.plugins.sources.paperclip import PaperclipSource

        source = PaperclipSource(query="vision-language pathology")
        assert isinstance(source, Source)

    def test_requires_non_empty_query(self) -> None:
        from paperwiki.plugins.sources.paperclip import PaperclipSource

        with pytest.raises(ValueError, match="query"):
            PaperclipSource(query="")

    def test_default_limit_and_bin(self) -> None:
        from paperwiki.plugins.sources.paperclip import PaperclipSource

        source = PaperclipSource(query="anything")
        assert source.limit == 20
        assert source.paperclip_bin == "paperclip"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestPaperclipSourceFetch:
    async def test_yields_papers_from_json_stdout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from paperwiki.plugins.sources.paperclip import PaperclipSource

        hits = [
            {
                "id": "10.1101/2024.01.01.123",
                "source": "biorxiv",
                "title": "A bioRxiv preprint",
                "authors": ["Alice Author", "Bob Bobson"],
                "abstract": "Some abstract.",
                "published": "2024-01-01",
                "url": "https://www.biorxiv.org/content/10.1101/2024.01.01.123",
            }
        ]
        _patch_subprocess(monkeypatch, stdout=_hits_to_stdout(hits))

        source = PaperclipSource(query="anything")
        papers = await _drain(source, _make_ctx())

        assert len(papers) == 1
        paper = papers[0]
        assert paper.canonical_id == "paperclip:bio_10.1101/2024.01.01.123"
        assert paper.title == "A bioRxiv preprint"
        assert [a.name for a in paper.authors] == ["Alice Author", "Bob Bobson"]

    async def test_pmc_hits_use_pmc_namespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from paperwiki.plugins.sources.paperclip import PaperclipSource

        hits = [
            {
                "id": "PMC987654",
                "source": "pmc",
                "title": "A PMC paper",
                "authors": ["A. Author"],
                "abstract": "...",
                "published": "2024-02-02",
            }
        ]
        _patch_subprocess(monkeypatch, stdout=_hits_to_stdout(hits))

        source = PaperclipSource(query="x")
        papers = await _drain(source, _make_ctx())
        assert papers[0].canonical_id == "paperclip:pmc_PMC987654"

    async def test_arxiv_external_id_promotes_to_arxiv_namespace(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When paperclip exposes an arXiv id, prefer ``arxiv:`` so dedup converges."""
        from paperwiki.plugins.sources.paperclip import PaperclipSource

        hits = [
            {
                "id": "10.1101/foo",
                "source": "biorxiv",
                "title": "Cross-listed",
                "authors": ["A"],
                "abstract": "...",
                "published": "2024-03-03",
                "external_ids": {"arxiv": "2403.12345"},
            }
        ]
        _patch_subprocess(monkeypatch, stdout=_hits_to_stdout(hits))

        source = PaperclipSource(query="x")
        papers = await _drain(source, _make_ctx())
        assert papers[0].canonical_id == "arxiv:2403.12345"

    async def test_passes_query_and_limit_to_cli(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from paperwiki.plugins.sources.paperclip import PaperclipSource

        captured: list[Sequence[str]] = []
        _patch_subprocess(monkeypatch, stdout=b"[]", capture_argv=captured)

        source = PaperclipSource(query="vision-language", limit=42)
        await _drain(source, _make_ctx())

        assert len(captured) == 1
        argv = list(captured[0])
        assert argv[0] == "paperclip"
        assert "search" in argv
        assert "vision-language" in argv
        assert "--limit" in argv
        assert "42" in argv
        assert "--json" in argv

    async def test_sources_filter_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from paperwiki.plugins.sources.paperclip import PaperclipSource

        captured: list[Sequence[str]] = []
        _patch_subprocess(monkeypatch, stdout=b"[]", capture_argv=captured)

        source = PaperclipSource(query="x", sources=["biorxiv", "pmc"])
        await _drain(source, _make_ctx())

        argv = list(captured[0])
        assert "--source" in argv
        # The two filters appear, order-insensitive.
        assert {"biorxiv", "pmc"}.issubset(set(argv))

    async def test_increments_counter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from paperwiki.plugins.sources.paperclip import PaperclipSource

        _patch_subprocess(monkeypatch, stdout=b"[]")
        source = PaperclipSource(query="x")
        ctx = _make_ctx()
        await _drain(source, ctx)
        assert ctx.counters["source.paperclip.requests"] == 1


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestPaperclipSourceErrors:
    async def test_missing_binary_raises_integration_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from paperwiki.plugins.sources.paperclip import PaperclipSource

        _patch_subprocess(monkeypatch, raises=FileNotFoundError)

        source = PaperclipSource(query="x")
        with pytest.raises(IntegrationError, match="paperclip not installed"):
            await _drain(source, _make_ctx())

    async def test_non_zero_exit_surfaces_stderr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from paperwiki.plugins.sources.paperclip import PaperclipSource

        _patch_subprocess(
            monkeypatch,
            returncode=2,
            stdout=b"",
            stderr=b"auth required: run `paperclip login`",
        )

        source = PaperclipSource(query="x")
        with pytest.raises(IntegrationError, match="paperclip login"):
            await _drain(source, _make_ctx())

    async def test_malformed_json_raises_integration_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from paperwiki.plugins.sources.paperclip import PaperclipSource

        _patch_subprocess(monkeypatch, stdout=b"<not json>")

        source = PaperclipSource(query="x")
        with pytest.raises(IntegrationError, match="JSON"):
            await _drain(source, _make_ctx())

    async def test_skips_individual_malformed_entries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One bad row in the result set must not lose the rest."""
        from paperwiki.plugins.sources.paperclip import PaperclipSource

        hits = [
            {"id": "bad-row"},  # missing title/abstract/authors
            {
                "id": "10.1101/good",
                "source": "biorxiv",
                "title": "Good row",
                "authors": ["A. Author"],
                "abstract": "Some abstract.",
                "published": "2024-04-04",
            },
        ]
        _patch_subprocess(monkeypatch, stdout=_hits_to_stdout(hits))

        source = PaperclipSource(query="x")
        papers = await _drain(source, _make_ctx())
        assert len(papers) == 1
        assert papers[0].title == "Good row"
