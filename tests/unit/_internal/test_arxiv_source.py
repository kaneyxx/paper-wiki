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

import fitz as _fitz
import httpx
import pytest

from paperwiki.core.errors import IntegrationError

if TYPE_CHECKING:
    from collections.abc import Iterable


# ---------------------------------------------------------------------------
# Helpers — synthetic tarballs
# ---------------------------------------------------------------------------


# 300x300 white PNG — large enough to pass the min-size filter (>200px on
# at least one axis, introduced in v0.3.20).
def _make_png(width: int = 300, height: int = 300) -> bytes:
    pix = _fitz.Pixmap(_fitz.csRGB, _fitz.IRect(0, 0, width, height), False)
    pix.set_rect(pix.irect, (255, 255, 255))
    return pix.tobytes("png")


_TINY_PNG = _make_png(300, 300)


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
        """``figures``, ``figure``, ``fig``, ``pics``, ``images``, ``img`` valid."""
        from paperwiki._internal.arxiv_source import extract_images_from_tarball

        tarball = tmp_path / "src.tar.gz"
        tarball.write_bytes(
            _build_tarball(
                [
                    ("paper/figure/zero.png", _TINY_PNG),  # singular form
                    ("paper/fig/a.png", _TINY_PNG),
                    ("paper/pics/b.jpg", _TINY_PNG),
                    ("paper/img/c.jpeg", _TINY_PNG),
                    ("paper/images/d.png", _TINY_PNG),
                ]
            )
        )
        out = tmp_path / "images"
        extracted = extract_images_from_tarball(tarball, out)
        assert len(extracted) == 5
        assert {p.name for p in extracted} == {
            "zero.png",
            "a.png",
            "b.jpg",
            "c.jpeg",
            "d.png",
        }

    def test_extracts_pdf_figures(self, tmp_path: Path) -> None:
        """Many arXiv papers ship vector PDFs as figures; keep them — Obsidian
        renders ``![[file.pdf]]`` as a first-page preview."""
        from paperwiki._internal.arxiv_source import extract_images_from_tarball

        tarball = tmp_path / "src.tar.gz"
        tarball.write_bytes(
            _build_tarball(
                [
                    ("latex/figure/Figure_1.pdf", b"%PDF-1.4 stub\n"),
                    ("latex/figure/Figure_2.pdf", b"%PDF-1.4 stub\n"),
                    ("latex/main.tex", b"\\documentclass{article}"),
                ]
            )
        )
        out = tmp_path / "images"
        extracted = extract_images_from_tarball(tarball, out)
        names = sorted(p.name for p in extracted)
        assert names == ["Figure_1.pdf", "Figure_2.pdf"]

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


# ---------------------------------------------------------------------------
# Priority 1 — min-size filter
# ---------------------------------------------------------------------------


class TestMinSizeFilter:
    def test_small_png_below_threshold_is_skipped(self, tmp_path: Path) -> None:
        """Images smaller than 200px on both axes must be filtered out."""
        from paperwiki._internal.arxiv_source import extract_images_from_tarball

        small_png = _make_png(50, 50)
        tarball = tmp_path / "src.tar.gz"
        tarball.write_bytes(
            _build_tarball(
                [
                    ("paper/figures/icon.png", small_png),
                    ("paper/figures/real.png", _TINY_PNG),  # 300x300 — passes
                ]
            )
        )
        out = tmp_path / "images"
        extracted = extract_images_from_tarball(tarball, out)
        # Only the 300x300 image should survive.
        assert [p.name for p in extracted] == ["real.png"]

    def test_wide_image_passes_even_when_short(self, tmp_path: Path) -> None:
        """An image 300x50 passes because one axis >= 200."""
        from paperwiki._internal.arxiv_source import extract_images_from_tarball

        wide_short = _make_png(300, 50)
        tarball = tmp_path / "src.tar.gz"
        tarball.write_bytes(_build_tarball([("paper/figures/banner.png", wide_short)]))
        out = tmp_path / "images"
        extracted = extract_images_from_tarball(tarball, out)
        assert [p.name for p in extracted] == ["banner.png"]


# ---------------------------------------------------------------------------
# Priority 2 — extract_root_pdfs_from_tarball
# ---------------------------------------------------------------------------


def _make_simple_pdf() -> bytes:
    """Build a minimal single-page PDF with a 400x300 white page via PyMuPDF."""
    import fitz

    doc = fitz.open()
    doc.new_page(width=400, height=300)
    return doc.tobytes()


class TestExtractRootPdfsFromTarball:
    def test_converts_root_pdf_to_png(self, tmp_path: Path) -> None:
        from paperwiki._internal.arxiv_source import extract_root_pdfs_from_tarball

        pdf_bytes = _make_simple_pdf()
        tarball = tmp_path / "src.tar.gz"
        tarball.write_bytes(
            _build_tarball(
                [
                    ("fig1.pdf", pdf_bytes),
                    ("main.tex", b"\\documentclass{article}"),
                ]
            )
        )
        out = tmp_path / "images"
        extracted = extract_root_pdfs_from_tarball(tarball, out)
        assert len(extracted) == 1
        assert extracted[0].suffix == ".png"
        assert extracted[0].name == "fig1_page1.png"
        assert extracted[0].is_file()

    def test_skips_compiled_pdf_names(self, tmp_path: Path) -> None:
        """main.pdf, paper.pdf, and <paper-id>.pdf must be skipped."""
        from paperwiki._internal.arxiv_source import extract_root_pdfs_from_tarball

        pdf_bytes = _make_simple_pdf()
        tarball = tmp_path / "src.tar.gz"
        tarball.write_bytes(
            _build_tarball(
                [
                    ("main.pdf", pdf_bytes),
                    ("paper.pdf", pdf_bytes),
                    ("2506.13063.pdf", pdf_bytes),
                    ("supplementary.pdf", pdf_bytes),  # should be kept
                ]
            )
        )
        out = tmp_path / "images"
        extracted = extract_root_pdfs_from_tarball(tarball, out, paper_id="2506.13063")
        names = [p.name for p in extracted]
        # Only supplementary survives.
        assert any("supplementary" in n for n in names), names
        assert not any("main_page" in n for n in names)
        assert not any("paper_page" in n for n in names)
        assert not any("2506" in n for n in names)

    def test_multi_page_pdf_generates_one_png_per_page(self, tmp_path: Path) -> None:
        """A 3-page PDF must produce page1, page2, page3 PNGs."""
        import fitz

        from paperwiki._internal.arxiv_source import extract_root_pdfs_from_tarball

        doc = fitz.open()
        for _ in range(3):
            doc.new_page(width=400, height=300)
        pdf_bytes = doc.tobytes()

        tarball = tmp_path / "src.tar.gz"
        tarball.write_bytes(_build_tarball([("diagram.pdf", pdf_bytes)]))
        out = tmp_path / "images"
        extracted = extract_root_pdfs_from_tarball(tarball, out)
        names = sorted(p.name for p in extracted)
        assert names == ["diagram_page1.png", "diagram_page2.png", "diagram_page3.png"]

    def test_returns_empty_when_no_root_pdfs(self, tmp_path: Path) -> None:
        from paperwiki._internal.arxiv_source import extract_root_pdfs_from_tarball

        tarball = tmp_path / "src.tar.gz"
        tarball.write_bytes(_build_tarball([("paper/figures/fig.png", _TINY_PNG)]))
        out = tmp_path / "images"
        extracted = extract_root_pdfs_from_tarball(tarball, out)
        assert extracted == []


# ---------------------------------------------------------------------------
# Priority 3 — extract_tikz_crop_from_pdf
# ---------------------------------------------------------------------------


def _make_pdf_with_figure_caption() -> bytes:
    """Build a minimal PDF page containing a 'Figure 1:' text block."""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4
    # Insert a mock figure area (filled rectangle) and then a caption below.
    page.draw_rect(fitz.Rect(72, 100, 523, 300), color=(0, 0, 0), fill=(0.8, 0.8, 0.8))
    page.insert_text(fitz.Point(72, 320), "Figure 1: A sample figure caption.", fontsize=10)
    return doc.tobytes()


class TestExtractTikzCropFromPdf:
    def test_crops_region_above_caption(self, tmp_path: Path) -> None:
        from paperwiki._internal.arxiv_source import extract_tikz_crop_from_pdf

        pdf_path = tmp_path / "paper.pdf"
        pdf_path.write_bytes(_make_pdf_with_figure_caption())

        out = tmp_path / "images"
        extracted = extract_tikz_crop_from_pdf(pdf_path, out, paper_id="test")
        assert len(extracted) >= 1, "should extract at least one cropped figure"
        for p in extracted:
            assert p.suffix == ".png"
            assert p.is_file()

    def test_returns_empty_when_no_pdf(self, tmp_path: Path) -> None:
        from paperwiki._internal.arxiv_source import extract_tikz_crop_from_pdf

        out = tmp_path / "images"
        extracted = extract_tikz_crop_from_pdf(tmp_path / "missing.pdf", out)
        assert extracted == []

    def test_caps_at_max_figures(self, tmp_path: Path) -> None:
        """No more than _TIKZ_MAX_FIGURES (8) crops per paper."""
        import fitz

        from paperwiki._internal.arxiv_source import (
            _TIKZ_MAX_FIGURES,
            extract_tikz_crop_from_pdf,
        )

        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        # Insert 12 figure captions spread down the page.
        y = 60.0
        for i in range(1, 13):
            page.draw_rect(fitz.Rect(72, y, 523, y + 40), color=(0, 0, 0), fill=(0.9, 0.9, 0.9))
            page.insert_text(
                fitz.Point(72, y + 55),
                f"Figure {i}: Caption text.",
                fontsize=10,
            )
            y += 65.0

        pdf_path = tmp_path / "paper.pdf"
        pdf_path.write_bytes(doc.tobytes())
        out = tmp_path / "images"
        extracted = extract_tikz_crop_from_pdf(pdf_path, out)
        assert len(extracted) <= _TIKZ_MAX_FIGURES


# ---------------------------------------------------------------------------
# _has_tikz helper
# ---------------------------------------------------------------------------


class TestHasTikz:
    def test_detects_tikzpicture(self, tmp_path: Path) -> None:
        from paperwiki._internal.arxiv_source import _has_tikz

        tarball = tmp_path / "src.tar.gz"
        tarball.write_bytes(
            _build_tarball(
                [
                    (
                        "paper/main.tex",
                        b"\\begin{tikzpicture}\n\\end{tikzpicture}",
                    )
                ]
            )
        )
        assert _has_tikz(tarball) is True

    def test_detects_pgfplots(self, tmp_path: Path) -> None:
        from paperwiki._internal.arxiv_source import _has_tikz

        tarball = tmp_path / "src.tar.gz"
        tarball.write_bytes(_build_tarball([("paper/main.tex", b"\\usepackage{pgfplots}")]))
        assert _has_tikz(tarball) is True

    def test_returns_false_without_tikz(self, tmp_path: Path) -> None:
        from paperwiki._internal.arxiv_source import _has_tikz

        tarball = tmp_path / "src.tar.gz"
        tarball.write_bytes(_build_tarball([("paper/main.tex", b"\\documentclass{article}")]))
        assert _has_tikz(tarball) is False
