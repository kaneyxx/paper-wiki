"""arXiv source-tarball helpers.

paper-wiki ships a tiny "image extraction" workflow that downloads the
arXiv source bundle for a paper and pulls out the real figures
(architecture diagrams, experimental plots, etc.) instead of just the
abstract or PDF page renders. This module is the file-IO half:

* :func:`download_arxiv_source` fetches
  ``https://arxiv.org/e-print/<arxiv-id>`` to a destination directory
  (delegates to the shared ``httpx.AsyncClient`` for retry / timeout
  semantics and the paper-wiki ``User-Agent``).
* :func:`extract_images_from_tarball` opens the tarball, walks its
  members, and copies image files (PNG / JPG / JPEG / GIF / WEBP) that
  live under common figure-directory names (``figures``, ``fig``,
  ``pics``, ``images``, ``img``) into a flat output directory.
  (Priority 1)
* :func:`extract_root_pdfs_from_tarball` finds standalone PDF files at
  the tarball root (not named like the paper's own compiled PDF) and
  converts each page to PNG via PyMuPDF. (Priority 2)
* :func:`extract_tikz_crop_from_pdf` detects TikZ in .tex source files
  and falls back to caption-aware crops of the compiled paper PDF.
  (Priority 3)

Both network functions raise :class:`IntegrationError` on failure so callers
can surface a useful message without cracking open httpx / tarfile
exceptions.

LLM-free by design — Claude does the synthesis on top of the
extracted images later, via SKILLs.
"""

from __future__ import annotations

import re
import tarfile
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import fitz  # type: ignore[import-untyped]  # PyMuPDF — hard dep since v0.3.20
from loguru import logger

from paperwiki.core.errors import IntegrationError

if TYPE_CHECKING:
    import httpx


_E_PRINT_URL = "https://arxiv.org/e-print/{arxiv_id}"
# Both ``figure`` (singular) and ``figures`` are common; we've also seen
# ``fig``, ``pics``, ``images``, ``img`` and ``Figures`` (capitalized).
# Match case-insensitively so the surface is forgiving.
_FIGURE_DIRS = {"figures", "figure", "fig", "pics", "images", "img"}
# PNGs / JPEGs cover most LaTeX-baked figures. PDFs are common too
# (vector figures); Obsidian renders ``![[file.pdf]]`` as a first-page
# preview so they're still useful to keep alongside.
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf"}

# Paper's own compiled PDF at root — skip these in Priority-2 scan.
_COMPILED_PDF_NAMES = {"main.pdf", "paper.pdf"}

# Minimum dimension for extracted images (pixels on at least one axis).
_MIN_SIZE_PX = 200

# Maximum caption-crop figures per paper (Priority 3).
_TIKZ_MAX_FIGURES = 8

# Caption regex for Priority-3 crop.
_CAPTION_RE = re.compile(r"^\s*Figure\s+\d+\s*[:.]", re.IGNORECASE)

# TikZ detection patterns in .tex source.
_TIKZ_PATTERNS = (
    rb"\\begin{tikzpicture}",
    rb"\\usepackage{pgfplots}",
    rb"\\usepackage[^}]*pgfplots",
)


async def download_arxiv_source(
    canonical_id: str,
    dest_dir: Path,
    *,
    http_client: httpx.AsyncClient,
) -> Path:
    """Download an arXiv source tarball into ``dest_dir`` and return its path.

    Parameters
    ----------
    canonical_id:
        Must start with ``arxiv:`` — paper-wiki's canonical namespace
        for arXiv papers. Other namespaces raise :class:`IntegrationError`
        because there is no arXiv source URL for them.
    dest_dir:
        Directory to write the downloaded tarball into. Created if
        missing.
    http_client:
        Pre-built ``httpx.AsyncClient``. The function does not own the
        lifecycle.

    Returns the path to the downloaded ``<arxiv-id>.tar.gz`` file. The
    file is written atomically: into a ``.partial`` sibling first, then
    renamed on successful download.
    """
    if not canonical_id.startswith("arxiv:"):
        msg = (
            f"download_arxiv_source: only ``arxiv:`` canonical ids have a "
            f"source-tarball URL; got {canonical_id!r}"
        )
        raise IntegrationError(msg)
    arxiv_id = canonical_id.split(":", 1)[1]
    url = _E_PRINT_URL.format(arxiv_id=arxiv_id)

    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"{arxiv_id}.tar.gz"
    partial = target.with_suffix(target.suffix + ".partial")

    response = await http_client.get(url, follow_redirects=True)
    if response.status_code >= 400:
        msg = f"download_arxiv_source: GET {url} returned HTTP {response.status_code}"
        raise IntegrationError(msg)

    partial.write_bytes(response.content)
    partial.rename(target)
    logger.info("arxiv_source.downloaded", canonical_id=canonical_id, bytes=target.stat().st_size)
    return target


def _passes_min_size(img_path: Path) -> bool:
    """Return True when the image is at least _MIN_SIZE_PX on at least one axis.

    Uses PyMuPDF's Pixmap loader for exact pixel dimensions; falls back to a
    file-size heuristic (>5 KB) when that fails.
    """
    try:
        pix = fitz.Pixmap(str(img_path))
        return bool(pix.width >= _MIN_SIZE_PX or pix.height >= _MIN_SIZE_PX)
    except Exception as exc:
        logger.debug("arxiv_source.min_size_check_failed", path=str(img_path), error=str(exc))

    # Fallback: use file size as a proxy (< 5 KB is almost certainly a
    # tiny icon/badge).
    try:
        return img_path.stat().st_size > 5_000
    except OSError:
        return False


def _passes_min_size_px(width: int, height: int) -> bool:
    """Size filter for already-decoded dimensions."""
    return width >= _MIN_SIZE_PX or height >= _MIN_SIZE_PX


def extract_images_from_tarball(tarball: Path, output_dir: Path) -> list[Path]:
    """Pull image files from common figure dirs inside ``tarball``. (Priority 1)

    Image files (extensions in :data:`_IMAGE_EXTENSIONS`) whose path
    contains any directory component matching :data:`_FIGURE_DIRS` are
    copied to ``output_dir`` under their basename only (paths are
    flattened). Non-image files and images outside the figure dirs are
    skipped — these are usually logos, license badges, or
    LaTeX-rendered glyphs that aren't paper figures.

    Applies minimum-size filter (>200 px on at least one axis) for PNG/JPG
    images to skip icons and UI fragments.

    Returns the sorted list of extracted image paths. Empty list when
    the tarball has no recognizable figures (legitimate for many older
    arXiv papers that submitted PDF only).

    Raises :class:`IntegrationError` when ``tarball`` is malformed.
    """
    extracted: list[Path] = []
    try:
        with tarfile.open(tarball, mode="r:*") as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                path = PurePosixPath(member.name)
                suffix = path.suffix.lower()
                if suffix not in _IMAGE_EXTENSIONS:
                    continue
                parents = {p.lower() for p in path.parts[:-1]}
                if not (parents & _FIGURE_DIRS):
                    continue

                data = tf.extractfile(member)
                if data is None:
                    continue
                output_dir.mkdir(parents=True, exist_ok=True)
                target = output_dir / path.name
                target.write_bytes(data.read())

                # Apply min-size filter for raster images (skip for PDFs —
                # they are kept as-is since we can't easily decode them here).
                if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp"} and not _passes_min_size(
                    target
                ):
                    target.unlink(missing_ok=True)
                    logger.debug(
                        "arxiv_source.skip_small_image",
                        name=path.name,
                        reason="below min size",
                    )
                    continue

                extracted.append(target)
    except tarfile.TarError as exc:
        msg = f"extract_images_from_tarball: malformed tarball {tarball}: {exc}"
        raise IntegrationError(msg) from exc

    return sorted(extracted)


def extract_root_pdfs_from_tarball(
    tarball: Path,
    output_dir: Path,
    *,
    paper_id: str = "",
) -> list[Path]:
    """Convert standalone PDF figures at the source root to PNG. (Priority 2)

    Scans the tarball root for ``.pdf`` files that are not the paper's own
    compiled PDF (``<paper-id>.pdf``, ``main.pdf``, ``paper.pdf``).  Each
    such PDF is opened with PyMuPDF and every page is rasterised at 3x
    scale into ``<figname>_page<N>.png`` under ``output_dir``.

    Returns extracted PNG paths sorted alphabetically.
    Silently skips PDFs that cannot be opened (malformed / encrypted).
    """
    compiled_pdf_names = set(_COMPILED_PDF_NAMES)
    if paper_id:
        compiled_pdf_names.add(f"{paper_id}.pdf")

    extracted: list[Path] = []
    try:
        with tarfile.open(tarball, mode="r:*") as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                path = PurePosixPath(member.name)
                # Only root-level files (no directory components beyond the
                # top-level tarball prefix, which we normalise away).
                parts = path.parts
                # Allow one prefix directory (common arXiv layout: paper/fig.pdf)
                # but reject deeper nesting.
                if len(parts) > 2:
                    continue
                if path.suffix.lower() != ".pdf":
                    continue
                stem_lower = path.name.lower()
                if stem_lower in compiled_pdf_names:
                    continue

                raw = tf.extractfile(member)
                if raw is None:
                    continue
                pdf_bytes = raw.read()
                figname = path.stem

                try:
                    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                except Exception as exc:
                    logger.warning(
                        "arxiv_source.skip_pdf",
                        name=path.name,
                        reason=str(exc),
                    )
                    continue

                output_dir.mkdir(parents=True, exist_ok=True)
                try:
                    for page_num in range(len(doc)):
                        page = doc[page_num]
                        pix = page.get_pixmap(matrix=fitz.Matrix(3, 3))
                        if not _passes_min_size_px(pix.width, pix.height):
                            logger.debug(
                                "arxiv_source.skip_small_pdf_page",
                                name=path.name,
                                page=page_num + 1,
                            )
                            continue
                        out_name = f"{figname}_page{page_num + 1}.png"
                        out_path = output_dir / out_name
                        pix.save(str(out_path))
                        extracted.append(out_path)
                finally:
                    doc.close()

    except tarfile.TarError as exc:
        msg = f"extract_root_pdfs_from_tarball: malformed tarball {tarball}: {exc}"
        raise IntegrationError(msg) from exc

    logger.info(
        "arxiv_source.root_pdfs_extracted",
        count=len(extracted),
    )
    return sorted(extracted)


def _has_tikz(tarball: Path) -> bool:
    """Return True when any .tex member of ``tarball`` uses TikZ/pgfplots."""
    try:
        with tarfile.open(tarball, mode="r:*") as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                if not member.name.lower().endswith(".tex"):
                    continue
                raw = tf.extractfile(member)
                if raw is None:
                    continue
                content = raw.read()
                for pattern in _TIKZ_PATTERNS:
                    if re.search(pattern, content):
                        return True
    except tarfile.TarError:
        pass
    return False


def extract_tikz_crop_from_pdf(
    paper_pdf: Path,
    output_dir: Path,
    *,
    paper_id: str = "",
) -> list[Path]:
    """Caption-aware crop of the compiled paper PDF for TikZ figures. (Priority 3)

    Scans every page for blocks matching ``Figure N:`` or ``Figure N.``
    caption text. For each caption, estimates the figure region above it
    (from the previous caption bottom or top-of-page + margin) and crops
    that rectangle out as a 3x-scale PNG.

    Caps output at :data:`_TIKZ_MAX_FIGURES` crops.  Skips crops smaller
    than :data:`_MIN_SIZE_PX` on both axes (too thin = header artefact).

    Returns sorted list of extracted PNG paths.
    """
    if not paper_pdf.is_file():
        logger.warning("arxiv_source.tikz_crop.missing_pdf", path=str(paper_pdf))
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    n = 0

    try:
        doc = fitz.open(str(paper_pdf))
    except Exception as exc:
        logger.warning("arxiv_source.tikz_crop.open_failed", error=str(exc))
        return []

    try:
        prev_caption_bottom: float = 0.0
        margin: float = 36.0

        for page_num in range(len(doc)):
            if n >= _TIKZ_MAX_FIGURES:
                break
            page = doc[page_num]
            blocks = page.get_text("blocks")
            prev_caption_bottom = 0.0  # reset per page

            for b in blocks:
                if n >= _TIKZ_MAX_FIGURES:
                    break
                # blocks: (x0, y0, x1, y1, text, block_no, block_type)
                if len(b) < 5:
                    continue
                text: str = b[4]
                if not _CAPTION_RE.match(text):
                    continue

                caption_bottom: float = float(b[3])
                fig_top = max(prev_caption_bottom + 5.0, float(page.rect.y0) + 30.0)

                if caption_bottom - fig_top < 50:
                    prev_caption_bottom = caption_bottom
                    continue  # too thin — probably a header artefact

                clip = fitz.Rect(
                    float(page.rect.x0) + margin,
                    fig_top,
                    float(page.rect.x1) - margin,
                    caption_bottom + 5.0,
                )
                pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), clip=clip)

                # Skip outputs below min size on BOTH axes (more lenient for
                # real figures which are usually wide).
                if pix.width < _MIN_SIZE_PX and pix.height < _MIN_SIZE_PX:
                    prev_caption_bottom = caption_bottom
                    continue

                n += 1
                suffix = f"_{paper_id}" if paper_id else ""
                out_path = output_dir / f"tikz_fig{n}{suffix}.png"
                pix.save(str(out_path))
                extracted.append(out_path)
                prev_caption_bottom = caption_bottom
    finally:
        doc.close()

    logger.info("arxiv_source.tikz_crop_done", count=len(extracted))
    return sorted(extracted)


__all__ = [
    "download_arxiv_source",
    "extract_images_from_tarball",
    "extract_root_pdfs_from_tarball",
    "extract_tikz_crop_from_pdf",
]
