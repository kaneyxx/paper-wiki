"""Unit tests for paperwiki.runners.extract_paper_images.

The runner orchestrates:
1. download arxiv source tarball
2. extract figures into Wiki/sources/<id>/images/
3. rewrite the ``## Figures`` section in the source .md with embeds

Tests stub the HTTP client with ``httpx.MockTransport`` and feed a
synthetic in-memory tarball, so they're hermetic and fast.
"""

from __future__ import annotations

import io
import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest

from paperwiki.core.errors import UserError
from paperwiki.core.models import (
    Author,
    Paper,
    Recommendation,
    ScoreBreakdown,
)
from paperwiki.plugins.backends.markdown_wiki import MarkdownWikiBackend

if TYPE_CHECKING:
    from collections.abc import Iterable


# Minimal 1x1 PNG.
_TINY_PNG = bytes.fromhex(
    "89504E470D0A1A0A0000000D49484452"
    "00000001000000010806000000"
    "1F15C489"
    "0000000A49444154789C6300010000050001"
    "0D0A2DB40000000049454E44AE426082"
)


def _build_tarball(files: Iterable[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in files:
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _make_recommendation(canonical_id: str = "arxiv:2506.13063") -> Recommendation:
    return Recommendation(
        paper=Paper(
            canonical_id=canonical_id,
            title="A Vision-Language Foundation Model",
            authors=[Author(name="Jane Doe")],
            abstract="Stub abstract.",
            published_at=datetime(2026, 4, 20, tzinfo=UTC),
            categories=["cs.CV"],
            landing_url=f"https://arxiv.org/abs/{canonical_id.split(':', 1)[1]}",
        ),
        score=ScoreBreakdown(composite=0.78),
    )


async def _seed_source(vault: Path, canonical_id: str) -> Path:
    backend = MarkdownWikiBackend(vault_path=vault)
    return await backend.upsert_paper(_make_recommendation(canonical_id))


def _mock_client(tarball_bytes: bytes | None, *, status: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if tarball_bytes is None:
            return httpx.Response(status)
        return httpx.Response(status, content=tarball_bytes)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------
# extract_paper_images
# ---------------------------------------------------------------------------


class TestExtractPaperImages:
    async def test_happy_path_downloads_extracts_and_embeds(self, tmp_path: Path) -> None:
        from paperwiki.runners import extract_paper_images as runner

        await _seed_source(tmp_path, "arxiv:2506.13063")
        tarball = _build_tarball(
            [
                ("paper/figures/teaser.png", _TINY_PNG),
                ("paper/figures/method.png", _TINY_PNG),
            ]
        )
        client = _mock_client(tarball)
        try:
            result = await runner.extract_paper_images(
                tmp_path, "arxiv:2506.13063", http_client=client
            )
        finally:
            await client.aclose()

        # Result counts what was extracted.
        assert result.canonical_id == "arxiv:2506.13063"
        assert result.image_count == 2
        # Files actually exist on disk.
        images_dir = tmp_path / "Wiki" / "sources" / "arxiv_2506.13063" / "images"
        assert images_dir.is_dir()
        names = sorted(p.name for p in images_dir.glob("*.png"))
        assert names == ["method.png", "teaser.png"]

    async def test_updates_figures_section_with_obsidian_embeds(self, tmp_path: Path) -> None:
        from paperwiki.runners import extract_paper_images as runner

        await _seed_source(tmp_path, "arxiv:2506.13063")
        tarball = _build_tarball([("paper/figures/teaser.png", _TINY_PNG)])
        client = _mock_client(tarball)
        try:
            await runner.extract_paper_images(tmp_path, "arxiv:2506.13063", http_client=client)
        finally:
            await client.aclose()

        body = (tmp_path / "Wiki" / "sources" / "arxiv_2506.13063.md").read_text(encoding="utf-8")
        # Embed uses Obsidian wikilink-with-width syntax pointing at the
        # extracted file.
        assert "![[arxiv_2506.13063/images/teaser.png" in body
        # Placeholder hint about extract-images is gone.
        assert "/paper-wiki:extract-images arxiv:2506.13063" not in body

    async def test_preserves_other_sections(self, tmp_path: Path) -> None:
        """Replacing ``## Figures`` must NOT touch ``## Notes`` or anything else."""
        from paperwiki.runners import extract_paper_images as runner

        path = await _seed_source(tmp_path, "arxiv:2506.13063")
        # Mark the Notes section so we can verify it survives.
        original = path.read_text(encoding="utf-8")
        path.write_text(
            original.replace(
                "_Your annotations and follow-up questions go here.",
                "MY_PRIVATE_NOTES — _Your annotations and follow-up questions go here.",
            ),
            encoding="utf-8",
        )

        tarball = _build_tarball([("paper/figures/teaser.png", _TINY_PNG)])
        client = _mock_client(tarball)
        try:
            await runner.extract_paper_images(tmp_path, "arxiv:2506.13063", http_client=client)
        finally:
            await client.aclose()

        body = path.read_text(encoding="utf-8")
        assert "MY_PRIVATE_NOTES" in body, "Notes section must survive image extraction"
        assert "## Abstract" in body
        assert "## Key Takeaways" in body

    async def test_zero_figures_keeps_helpful_placeholder(self, tmp_path: Path) -> None:
        from paperwiki.runners import extract_paper_images as runner

        await _seed_source(tmp_path, "arxiv:2506.13063")
        tarball = _build_tarball([("paper/main.tex", b"\\documentclass{article}")])
        client = _mock_client(tarball)
        try:
            result = await runner.extract_paper_images(
                tmp_path, "arxiv:2506.13063", http_client=client
            )
        finally:
            await client.aclose()

        assert result.image_count == 0
        body = (tmp_path / "Wiki" / "sources" / "arxiv_2506.13063.md").read_text(encoding="utf-8")
        # Body still has Figures section with a "no figures found" note.
        assert "## Figures" in body
        assert "no figures" in body.lower() or "0 figures" in body.lower()

    async def test_missing_source_file_raises_user_error(self, tmp_path: Path) -> None:
        from paperwiki.runners import extract_paper_images as runner

        client = _mock_client(b"")
        try:
            with pytest.raises(UserError, match="Wiki/sources"):
                await runner.extract_paper_images(tmp_path, "arxiv:9999.99999", http_client=client)
        finally:
            await client.aclose()

    async def test_idempotent_re_extraction_skips_when_force_false(self, tmp_path: Path) -> None:
        """Running twice without --force should re-use the cached tarball."""
        from paperwiki.runners import extract_paper_images as runner

        await _seed_source(tmp_path, "arxiv:2506.13063")
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(
                200,
                content=_build_tarball([("paper/figures/x.png", _TINY_PNG)]),
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            await runner.extract_paper_images(tmp_path, "arxiv:2506.13063", http_client=client)
            await runner.extract_paper_images(tmp_path, "arxiv:2506.13063", http_client=client)
        finally:
            await client.aclose()
        # Second call hits the cache; only one HTTP fetch.
        assert call_count == 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli:
    def test_emits_valid_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """CLI prints JSON with canonical_id + image_count + image paths.

        Sync test (CliRunner uses ``asyncio.run`` internally, which would
        clash with pytest-asyncio's auto-mode loop on async tests).
        """
        import asyncio as _asyncio

        from paperwiki.runners import extract_paper_images as runner

        # Seed the source file in a one-off loop.
        loop = _asyncio.new_event_loop()
        try:
            loop.run_until_complete(_seed_source(tmp_path, "arxiv:2506.13063"))
        finally:
            loop.close()

        tarball = _build_tarball([("paper/figures/teaser.png", _TINY_PNG)])

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=tarball)

        def _stub_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
            return httpx.AsyncClient(transport=httpx.MockTransport(handler))

        # Patch the symbol the runner module imported at module load time.
        monkeypatch.setattr(runner, "build_client", _stub_client)

        from typer.testing import CliRunner

        cli = CliRunner()
        result = cli.invoke(runner.app, [str(tmp_path), "arxiv:2506.13063"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["canonical_id"] == "arxiv:2506.13063"
        assert payload["image_count"] == 1
        assert any(p.endswith("teaser.png") for p in payload["images"])
