"""Unit tests for paperwiki.plugins.sources.paperclip.

paperclip's CLI flow is two-step:

1. ``paperclip search QUERY -n N``  →  stdout has ``[s_<hex>]``
2. ``paperclip results <session> --save <file>``  →  writes a CSV

All tests stub ``asyncio.create_subprocess_exec`` so the suite is
hermetic. The second call also writes a real CSV file to the path the
plugin requested so the CSV parser has something to read.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from paperwiki.core.errors import IntegrationError
from paperwiki.core.models import RunContext

if TYPE_CHECKING:
    from collections.abc import Sequence


# ---------------------------------------------------------------------------
# Test stubs
# ---------------------------------------------------------------------------


class _FakeProcess:
    """Stand-in for ``asyncio.subprocess.Process``."""

    def __init__(self, *, returncode: int, stdout: bytes, stderr: bytes) -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


class _ScriptedSubprocess:
    """Replays a sequence of canned ``create_subprocess_exec`` results.

    Each call pops the next entry from ``responses``. The second-step
    response (``paperclip results --save``) optionally writes a CSV
    file to the path captured from argv so the plugin's CSV parser
    can consume it.
    """

    def __init__(
        self,
        responses: list[dict[str, object]],
        captured_argv: list[Sequence[str]] | None = None,
    ) -> None:
        self._responses = list(responses)
        self.captured_argv = captured_argv

    async def __call__(self, *argv: str, **kwargs: object) -> _FakeProcess:
        if self.captured_argv is not None:
            self.captured_argv.append(argv)
        if not self._responses:
            msg = "_ScriptedSubprocess ran out of canned responses"
            raise AssertionError(msg)
        spec = self._responses.pop(0)
        if spec.get("raises"):
            raise FileNotFoundError("paperclip")
        # If this response is for `paperclip results --save <path>`, write
        # the CSV body to that path so the parser sees real bytes.
        csv_body = spec.get("write_csv")
        if csv_body is not None:
            argv_list = list(argv)
            if "--save" in argv_list:
                save_idx = argv_list.index("--save")
                target = Path(argv_list[save_idx + 1])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(str(csv_body), encoding="utf-8")
        return _FakeProcess(
            returncode=int(spec.get("returncode", 0)),  # type: ignore[arg-type]
            stdout=spec.get("stdout", b""),  # type: ignore[arg-type]
            stderr=spec.get("stderr", b""),  # type: ignore[arg-type]
        )


def _patch_with_responses(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[dict[str, object]],
    *,
    captured: list[Sequence[str]] | None = None,
) -> None:
    from paperwiki.plugins.sources import paperclip as paperclip_module

    scripted = _ScriptedSubprocess(responses, captured_argv=captured)
    monkeypatch.setattr(paperclip_module.asyncio, "create_subprocess_exec", scripted)


def _make_ctx() -> RunContext:
    return RunContext(target_date=datetime(2026, 4, 25, tzinfo=UTC), config_snapshot={})


async def _drain(source: object, ctx: RunContext) -> list[object]:
    return [paper async for paper in source.fetch(ctx)]  # type: ignore[attr-defined]


# Canned shapes mirroring real paperclip output.
_REAL_SEARCH_STDOUT = (
    b"Found 2 papers  [s_0e0ab6cd]\n"
    b"\n"
    b"  1. The Protein Design Archive\n"
    b"     Marta Chronowska, Christopher Wood\n"
    b"     bio_dca47d1579b6 - bioRxiv - 2024-09-05\n"
    b"\n"
    b"  2. Cell-free protein synthesis\n"
    b"     Ella Thornton, Sarah Paterson\n"
    b"     PMC11344276 - Protein Science - 2024-08-24\n"
    b"\n"
    b"[442ms, saved to s_0e0ab6cd]\n"
)

_REAL_RESULTS_CSV = (
    "title,authors,id,source,date,url,abstract\n"
    'The Protein Design Archive,"Marta Chronowska, Christopher Wood",'
    "bio_dca47d1579b6,bioRxiv,2024-09-05,"
    "https://doi.org/10.1101/2024.09.05.611465,"
    "A catalog of designed proteins with trend analysis.\n"
    'Cell-free protein synthesis,"Ella Thornton, Sarah Paterson",'
    "PMC11344276,Protein Science,2024-08-24,"
    "https://doi.org/10.1002/pro.5148,"
    "Cell-free synthesis is rapid and versatile for screening designs.\n"
)


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

    def test_rejects_zero_or_negative_limit(self) -> None:
        from paperwiki.plugins.sources.paperclip import PaperclipSource

        with pytest.raises(ValueError, match="limit"):
            PaperclipSource(query="x", limit=0)

    def test_default_limit_and_bin(self) -> None:
        from paperwiki.plugins.sources.paperclip import PaperclipSource

        source = PaperclipSource(query="anything")
        assert source.limit == 20
        assert source.paperclip_bin == "paperclip"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestPaperclipSourceFetch:
    async def test_yields_papers_from_real_csv_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from paperwiki.plugins.sources.paperclip import PaperclipSource

        _patch_with_responses(
            monkeypatch,
            [
                {"stdout": _REAL_SEARCH_STDOUT, "stderr": b""},
                {"stdout": b"  Saved 2 papers\n", "write_csv": _REAL_RESULTS_CSV},
            ],
        )

        source = PaperclipSource(query="protein design")
        papers = await _drain(source, _make_ctx())

        assert len(papers) == 2
        ids = {p.canonical_id for p in papers}
        assert ids == {"paperclip:bio_dca47d1579b6", "paperclip:pmc_PMC11344276"}
        # Title preserved verbatim.
        assert any(p.title == "The Protein Design Archive" for p in papers)
        # Authors split on commas, trimmed.
        thornton = next(p for p in papers if p.canonical_id.endswith("11344276"))
        assert [a.name for a in thornton.authors] == ["Ella Thornton", "Sarah Paterson"]
        # Source/journal lands in categories so downstream filters can use it.
        assert "bioRxiv" in {c for p in papers for c in p.categories}

    async def test_search_argv_carries_limit_and_filters(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from paperwiki.plugins.sources.paperclip import PaperclipSource

        captured: list[Sequence[str]] = []
        _patch_with_responses(
            monkeypatch,
            [
                {"stdout": _REAL_SEARCH_STDOUT, "stderr": b""},
                {"stdout": b"", "write_csv": _REAL_RESULTS_CSV},
            ],
            captured=captured,
        )

        source = PaperclipSource(
            query="vision-language",
            limit=42,
            since_days=14,
            journal="Nature",
            document_type="meeting",
        )
        await _drain(source, _make_ctx())

        # Two calls: search then results --save
        assert len(captured) == 2
        search_argv = list(captured[0])
        results_argv = list(captured[1])
        assert search_argv[:3] == ["paperclip", "search", "vision-language"]
        assert "-n" in search_argv
        assert "42" in search_argv
        assert "--since" in search_argv
        assert "14d" in search_argv
        assert "--journal" in search_argv
        assert "Nature" in search_argv
        assert "-T" in search_argv
        assert "meeting" in search_argv
        # Second call exports the captured session id from the first stdout.
        assert results_argv[:3] == ["paperclip", "results", "s_0e0ab6cd"]
        assert "--save" in results_argv

    async def test_increments_counter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from paperwiki.plugins.sources.paperclip import PaperclipSource

        _patch_with_responses(
            monkeypatch,
            [
                {"stdout": _REAL_SEARCH_STDOUT},
                {"stdout": b"", "write_csv": _REAL_RESULTS_CSV},
            ],
        )
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

        _patch_with_responses(monkeypatch, [{"raises": True}])
        source = PaperclipSource(query="x")
        with pytest.raises(IntegrationError, match="paperclip not installed"):
            await _drain(source, _make_ctx())

    async def test_search_non_zero_exit_surfaces_stderr(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from paperwiki.plugins.sources.paperclip import PaperclipSource

        _patch_with_responses(
            monkeypatch,
            [
                {
                    "returncode": 2,
                    "stdout": b"",
                    "stderr": b"auth required: run `paperclip login`",
                }
            ],
        )
        source = PaperclipSource(query="x")
        with pytest.raises(IntegrationError, match="paperclip login"):
            await _drain(source, _make_ctx())

    async def test_search_without_session_id_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from paperwiki.plugins.sources.paperclip import PaperclipSource

        _patch_with_responses(
            monkeypatch,
            [{"stdout": b"Found 0 papers\n", "stderr": b""}],
        )
        source = PaperclipSource(query="x")
        with pytest.raises(IntegrationError, match="no session id"):
            await _drain(source, _make_ctx())

    async def test_results_save_no_file_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If `paperclip results --save` exits 0 but writes nothing, surface it."""
        from paperwiki.plugins.sources.paperclip import PaperclipSource

        _patch_with_responses(
            monkeypatch,
            [
                {"stdout": _REAL_SEARCH_STDOUT, "stderr": b""},
                {"stdout": b"", "stderr": b""},  # no write_csv → no file written
            ],
        )
        source = PaperclipSource(query="x")
        with pytest.raises(IntegrationError, match="wrote no file"):
            await _drain(source, _make_ctx())

    async def test_skips_individual_malformed_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Rows missing required fields (title, authors, date) are skipped."""
        from paperwiki.plugins.sources.paperclip import PaperclipSource

        bad_then_good = (
            "title,authors,id,source,date,url,abstract\n"
            ",,bio_bad,bioRxiv,not-a-date,,\n"  # missing title + bad date
            "Good Paper,A. Author,PMC123,Journal,2024-01-01,"
            "https://example.org,A real abstract.\n"
        )
        _patch_with_responses(
            monkeypatch,
            [
                {"stdout": _REAL_SEARCH_STDOUT, "stderr": b""},
                {"stdout": b"", "write_csv": bad_then_good},
            ],
        )

        source = PaperclipSource(query="x")
        papers = await _drain(source, _make_ctx())
        assert len(papers) == 1
        assert papers[0].canonical_id == "paperclip:pmc_PMC123"
        assert papers[0].title == "Good Paper"

    async def test_empty_abstract_kept_with_placeholder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Real paperclip CSVs frequently ship empty abstracts; keep the row."""
        from paperwiki.plugins.sources.paperclip import PaperclipSource

        empty_abstract_csv = (
            "title,authors,id,source,date,url,abstract\n"
            "A Paper Without Abstract,A. Author,bio_abc123,bioRxiv,"
            "2026-02-01,https://example.org,\n"
        )
        _patch_with_responses(
            monkeypatch,
            [
                {"stdout": _REAL_SEARCH_STDOUT, "stderr": b""},
                {"stdout": b"", "write_csv": empty_abstract_csv},
            ],
        )

        source = PaperclipSource(query="x")
        papers = await _drain(source, _make_ctx())
        assert len(papers) == 1
        assert papers[0].title == "A Paper Without Abstract"
        # Placeholder makes the upstream gap visible without breaking
        # downstream consumers that expect a non-empty abstract.
        assert "no abstract" in papers[0].abstract.lower()
