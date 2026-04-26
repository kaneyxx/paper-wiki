"""Unit tests for paperwiki._internal.arxiv_source.

The module:
- downloads the arxiv source tarball (``https://arxiv.org/e-print/<id>``)
  via our shared ``httpx.AsyncClient``,
- extracts image files (PNG, JPG, JPEG, GIF, WEBP) from common
  figure-directory layouts inside the tarball.

Tests build a small in-memory tarball (no network) and stub the HTTP
layer so they're hermetic on CI.
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest

from paperwiki.core.errors import IntegrationError

if TYPE_CHECKING:
    from collections.abc import Iterable


# ---------------------------------------------------------------------------
# Helpers — synthetic tarballs
# ---------------------------------------------------------------------------

# Minimal 1x1 PNG (8-byte signature + IHDR + IDAT + IEND).
_TINY_PNG = bytes.fromhex(
    "89504E470D0A1A0A"
    "0000000D49484452"
    "00000001000000010806000000"
    "1F15C489"
    "0000000A49444154789C6300010000050001"
    "0D0A2DB4"
    "0000000049454E44AE426082"
)


def _build_tarball(files: Iterable[tuple[str, bytes]]) -> bytes:
    """Build a .tar.gz in memory from ``[(arcname, body), ...]``."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in files:
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# extract_images_from_tarball
# ---------------------------------------------------------------------------


class TestExtractImagesFromTarball:
    def test_pulls_images_from_figures_directory(self, tmp_path: Path) -> None:
        from paperwiki._internal.arxiv_source import extract_images_from_tarball

        tarball_bytes = _build_tarball(
            [
                ("paper/main.tex", b"\\documentclass{article}"),
                ("paper/figures/teaser.png", _TINY_PNG),
                ("paper/figures/method.png", _TINY_PNG),
                ("paper/refs.bib", b"@article{...}"),
            ]
        )
        tarball = tmp_path / "src.tar.gz"
        tarball.write_bytes(tarball_bytes)
        out = tmp_path / "images"

        extracted = extract_images_from_tarball(tarball, out)
        names = sorted(p.name for p in extracted)
        assert names == ["method.png", "teaser.png"]
        # Files actually exist on disk.
        for p in extracted:
            assert p.is_file()
            assert p.stat().st_size > 0

    def test_handles_alternate_figure_dirs(self, tmp_path: Path) -> None:
        """``figures``, ``fig``, ``pics``, ``images``, ``img`` are all valid."""
        from paperwiki._internal.arxiv_source import extract_images_from_tarball

        tarball = tmp_path / "src.tar.gz"
        tarball.write_bytes(
            _build_tarball(
                [
                    ("paper/fig/a.png", _TINY_PNG),
                    ("paper/pics/b.jpg", _TINY_PNG),
                    ("paper/img/c.jpeg", _TINY_PNG),
                    ("paper/images/d.png", _TINY_PNG),
                ]
            )
        )
        out = tmp_path / "images"
        extracted = extract_images_from_tarball(tarball, out)
        assert len(extracted) == 4
        assert {p.name for p in extracted} == {"a.png", "b.jpg", "c.jpeg", "d.png"}

    def test_skips_images_outside_figure_dirs(self, tmp_path: Path) -> None:
        """A bare ``logo.png`` at the root is probably not a paper figure."""
        from paperwiki._internal.arxiv_source import extract_images_from_tarball

        tarball = tmp_path / "src.tar.gz"
        tarball.write_bytes(
            _build_tarball(
                [
                    ("paper/logo.png", _TINY_PNG),
                    ("paper/figures/real_figure.png", _TINY_PNG),
                ]
            )
        )
        out = tmp_path / "images"
        extracted = extract_images_from_tarball(tarball, out)
        assert [p.name for p in extracted] == ["real_figure.png"]

    def test_skips_non_image_files(self, tmp_path: Path) -> None:
        from paperwiki._internal.arxiv_source import extract_images_from_tarball

        tarball = tmp_path / "src.tar.gz"
        tarball.write_bytes(
            _build_tarball(
                [
                    ("paper/figures/method.tex", b"\\section{Method}"),
                    ("paper/figures/method.png", _TINY_PNG),
                ]
            )
        )
        out = tmp_path / "images"
        extracted = extract_images_from_tarball(tarball, out)
        assert [p.name for p in extracted] == ["method.png"]

    def test_returns_empty_for_tarball_without_figures(self, tmp_path: Path) -> None:
        from paperwiki._internal.arxiv_source import extract_images_from_tarball

        tarball = tmp_path / "src.tar.gz"
        tarball.write_bytes(_build_tarball([("paper/main.tex", b"\\documentclass{article}")]))
        out = tmp_path / "images"
        extracted = extract_images_from_tarball(tarball, out)
        assert extracted == []
        # Output dir is fine to leave empty (or not exist) — caller handles.

    def test_corrupt_tarball_raises_integration_error(self, tmp_path: Path) -> None:
        from paperwiki._internal.arxiv_source import extract_images_from_tarball

        tarball = tmp_path / "broken.tar.gz"
        tarball.write_bytes(b"not a tarball")
        out = tmp_path / "images"
        with pytest.raises(IntegrationError, match="tarball"):
            extract_images_from_tarball(tarball, out)


# ---------------------------------------------------------------------------
# download_arxiv_source
# ---------------------------------------------------------------------------


class TestDownloadArxivSource:
    async def test_downloads_to_dest_for_arxiv_canonical_id(self, tmp_path: Path) -> None:
        from paperwiki._internal.arxiv_source import download_arxiv_source

        tarball_bytes = _build_tarball([("paper/figures/x.png", _TINY_PNG)])

        def handler(request: httpx.Request) -> httpx.Response:
            assert "/e-print/2506.13063" in str(request.url)
            return httpx.Response(200, content=tarball_bytes)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            path = await download_arxiv_source("arxiv:2506.13063", tmp_path, http_client=client)
        finally:
            await client.aclose()

        assert path.is_file()
        assert path.read_bytes() == tarball_bytes

    async def test_rejects_non_arxiv_canonical_id(self, tmp_path: Path) -> None:
        from paperwiki._internal.arxiv_source import download_arxiv_source

        client = httpx.AsyncClient()
        try:
            with pytest.raises(IntegrationError, match="arxiv"):
                await download_arxiv_source("paperclip:bio_xyz", tmp_path, http_client=client)
        finally:
            await client.aclose()

    async def test_http_failure_raises_integration_error(self, tmp_path: Path) -> None:
        from paperwiki._internal.arxiv_source import download_arxiv_source

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(IntegrationError, match="404"):
                await download_arxiv_source("arxiv:9999.99999", tmp_path, http_client=client)
        finally:
            await client.aclose()
