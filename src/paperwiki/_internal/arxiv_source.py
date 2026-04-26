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

Both functions raise :class:`IntegrationError` on failure so callers
can surface a useful message without cracking open httpx / tarfile
exceptions.

LLM-free by design — Claude does the synthesis on top of the
extracted images later, via SKILLs.
"""

from __future__ import annotations

import tarfile
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from loguru import logger

from paperwiki.core.errors import IntegrationError

if TYPE_CHECKING:
    import httpx


_E_PRINT_URL = "https://arxiv.org/e-print/{arxiv_id}"
_FIGURE_DIRS = {"figures", "fig", "pics", "images", "img"}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


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


def extract_images_from_tarball(tarball: Path, output_dir: Path) -> list[Path]:
    """Pull image files from common figure dirs inside ``tarball``.

    Image files (extensions in :data:`_IMAGE_EXTENSIONS`) whose path
    contains any directory component matching :data:`_FIGURE_DIRS` are
    copied to ``output_dir`` under their basename only (paths are
    flattened). Non-image files and images outside the figure dirs are
    skipped — these are usually logos, license badges, or
    LaTeX-rendered glyphs that aren't paper figures.

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
                if path.suffix.lower() not in _IMAGE_EXTENSIONS:
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
                extracted.append(target)
    except tarfile.TarError as exc:
        msg = f"extract_images_from_tarball: malformed tarball {tarball}: {exc}"
        raise IntegrationError(msg) from exc

    return sorted(extracted)


__all__ = ["download_arxiv_source", "extract_images_from_tarball"]
